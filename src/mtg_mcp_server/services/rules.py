"""MTG Comprehensive Rules service -- download, parse, and index.

Downloads the official Comprehensive Rules text file, parses it into
searchable indexes (rules by number, glossary by term), and serves lookups
from memory.  File-based service (not ``BaseClient``) -- same lifecycle
pattern as ``ScryfallBulkClient``.
"""

from __future__ import annotations

import asyncio
import re
import time

import httpx
import structlog

from mtg_mcp_server.services.base import DEFAULT_USER_AGENT, ServiceError
from mtg_mcp_server.types import GlossaryEntry, Rule

__all__ = ["RULES_PAGE_URL", "RulesError", "RulesService"]

log = structlog.get_logger(service="rules")

# Rule numbers: digits, dot, digits, optional letter suffix
# e.g., "100.1", "100.2a", "704.5k", "702.19b"
_RULE_NUMBER_RE = re.compile(r"^(\d{3}\.\d+[a-z]?)\.?\s")

# Section headers in the table of contents: "1. Game Concepts"
_SECTION_HEADER_RE = re.compile(r"^(\d+)\.\s+(.+)$")

# Official rules page, which links the current Comprehensive Rules TXT file
RULES_PAGE_URL = "https://magic.wizards.com/en/rules"
_RULES_TXT_LINK_RE = re.compile(
    r"https://media\.wizards\.com/\d{4}/downloads/MagicCompRules \d{8}\.txt"
)

# Delay before retrying a failed refresh (seconds)
_REFRESH_RETRY_SECONDS = 300


class RulesError(ServiceError):
    """Base exception for Comprehensive Rules service errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=None)


class RulesService:
    """Index and query the MTG Comprehensive Rules.

    Not a ``BaseClient`` subclass -- downloads a plain-text file, parses it
    into in-memory dicts, and serves lookups.  Lazy-loads on first access.

    Args:
        rules_url: URL of the Comprehensive Rules text file. Used as-is, or as
            the fallback when discovery via ``rules_page_url`` fails.
        refresh_hours: Hours between refresh checks.
        rules_page_url: Page to discover the current rules URL from. ``None``
            disables discovery.
    """

    def __init__(
        self, rules_url: str, refresh_hours: int = 168, rules_page_url: str | None = None
    ) -> None:
        self._rules_url = rules_url
        self._rules_page_url = rules_page_url
        self._refresh_seconds = refresh_hours * 3600

        self._rules: dict[str, Rule] = {}
        self._glossary: dict[str, GlossaryEntry] = {}
        self._sections: dict[str, str] = {}  # section number -> name

        self._loaded_at: float = 0.0  # monotonic timestamp; 0 = never loaded
        self._load_lock = asyncio.Lock()

    async def ensure_loaded(self) -> None:
        """Download and parse rules if not loaded or stale.

        On first load failure the error propagates. On refresh failure
        with existing data, logs a warning and serves stale data.
        """
        if not self._is_stale():
            return

        async with self._load_lock:
            if not self._is_stale():
                return

            is_refresh = self._loaded_at != 0.0
            log.info("rules.loading", is_refresh=is_refresh)

            try:
                raw_text = await self._download()
                self._parse(raw_text)
                self._loaded_at = time.monotonic()
                log.info(
                    "rules.loaded",
                    rule_count=len(self._rules),
                    glossary_count=len(self._glossary),
                    section_count=len(self._sections),
                )
            except Exception as exc:
                if is_refresh:
                    log.warning(
                        "rules.refresh_failed",
                        exc_info=True,
                        retry_in_seconds=_REFRESH_RETRY_SECONDS,
                    )
                    self._loaded_at = (
                        time.monotonic() - self._refresh_seconds + _REFRESH_RETRY_SECONDS
                    )
                    return
                if isinstance(exc, RulesError):
                    raise
                raise RulesError(f"Unexpected error loading rules: {exc}") from exc

    # -------------------------------------------------------------------
    # Public query methods
    # -------------------------------------------------------------------

    async def lookup_by_number(self, number: str) -> Rule | None:
        """Look up a rule by its number (e.g. ``'704.5k'``). O(1).

        Normalizes trailing periods (``"100.1."`` -> ``"100.1"``).
        """
        await self.ensure_loaded()
        normalized = number.rstrip(".")
        return self._rules.get(normalized)

    async def keyword_search(self, keyword: str) -> list[Rule]:
        """Search rule text for a keyword, ranked by relevance.

        Ranking priority:
        1. Exact match (entire rule text equals the keyword)
        2. Word boundary match (keyword appears as a whole word)
        3. Substring match

        Returns at most 20 results.
        """
        await self.ensure_loaded()
        keyword_lower = keyword.lower()
        word_pattern = re.compile(r"\b" + re.escape(keyword_lower) + r"\b", re.IGNORECASE)

        exact: list[Rule] = []
        word_boundary: list[Rule] = []
        substring: list[Rule] = []

        for rule in self._rules.values():
            text_lower = rule.text.lower()
            if keyword_lower not in text_lower:
                continue
            if text_lower.strip() == keyword_lower:
                exact.append(rule)
            elif word_pattern.search(rule.text):
                word_boundary.append(rule)
            else:
                substring.append(rule)

        combined = exact + word_boundary + substring
        return combined[:20]

    async def glossary_lookup(self, term: str) -> GlossaryEntry | None:
        """Look up a glossary term. Case-insensitive exact match."""
        await self.ensure_loaded()
        return self._glossary.get(term.lower())

    async def list_keywords(self) -> list[dict[str, str]]:
        """Return all glossary entries that are keywords (702.x rules).

        A glossary entry is considered a keyword if its definition references
        a 702.x rule number.
        """
        await self.ensure_loaded()
        result: list[dict[str, str]] = []
        for entry in self._glossary.values():
            if _is_keyword_glossary_entry(entry):
                result.append({"term": entry.term, "definition": entry.definition})
        return sorted(result, key=lambda d: d["term"])

    async def list_sections(self) -> list[dict[str, str]]:
        """Return the section index as a list of dicts with number and name."""
        await self.ensure_loaded()
        return [
            {"number": num, "name": name}
            for num, name in sorted(self._sections.items(), key=lambda x: int(x[0]))
        ]

    async def resolve_section(self, section: str) -> str | None:
        """Resolve a section name or number to a numeric prefix.

        Accepts either a numeric prefix (e.g. "7") which is returned as-is,
        or a text name (e.g. "combat", "stack") which is matched case-insensitively
        against section names.  Returns ``None`` if no match is found.
        """
        await self.ensure_loaded()
        # Already numeric — return directly
        if section.replace(".", "").isdigit():
            return section
        # Text name — search sections for a substring match
        lower = section.lower()
        for num, name in self._sections.items():
            if lower in name.lower():
                return num
        return None

    # -------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------

    def _is_stale(self) -> bool:
        """Check if the loaded data has exceeded the refresh interval."""
        if self._loaded_at == 0.0:
            return True
        return (time.monotonic() - self._loaded_at) >= self._refresh_seconds

    async def _download(self) -> str:
        """Download the Comprehensive Rules text file.

        Returns the file content as a string with BOM stripped.
        """
        try:
            async with httpx.AsyncClient(
                timeout=60.0,
                headers={"User-Agent": DEFAULT_USER_AGENT},
            ) as http:
                url = await self._discover_url(http)
                log.info("rules.downloading", url=url)
                response = await http.get(url)
                if response.status_code != 200:
                    hint = ""
                    if response.status_code == 404:
                        hint = (
                            " — WotC changes the rules URL with each update (~4x/year). "
                            "Set MTG_MCP_RULES_URL to the current URL from "
                            "https://magic.wizards.com/en/rules"
                        )
                    raise RulesError(
                        f"HTTP {response.status_code} downloading rules from {url}{hint}"
                    )
                # Decode as UTF-8 and strip BOM if present
                try:
                    text = response.content.decode("utf-8-sig")
                except UnicodeDecodeError as exc:
                    raise RulesError(
                        f"Rules file is not valid UTF-8 "
                        f"(got {len(response.content)} bytes from {url})"
                    ) from exc
                return text
        except httpx.RequestError as exc:
            raise RulesError(f"Network error downloading rules: {exc}") from exc

    async def _discover_url(self, http: httpx.AsyncClient) -> str:
        """Find the current rules TXT URL on the rules page, else the configured URL."""
        if self._rules_page_url is None:
            return self._rules_url
        try:
            response = await http.get(self._rules_page_url, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError:
            log.warning("rules.discovery_failed", page=self._rules_page_url, exc_info=True)
            return self._rules_url
        match = _RULES_TXT_LINK_RE.search(response.text)
        if match is None:
            log.warning("rules.discovery_no_link", page=self._rules_page_url)
            return self._rules_url
        return match.group().replace(" ", "%20")

    def _parse(self, text: str) -> None:
        """Parse the Comprehensive Rules text into indexed data structures.

        Populates ``_rules``, ``_glossary``, and ``_sections``.
        """
        lines = text.splitlines()

        rules: dict[str, Rule] = {}
        glossary: dict[str, GlossaryEntry] = {}
        sections: dict[str, str] = {}

        # Parse into three regions: pre-rules, rules, glossary
        state = "preamble"
        current_rule_number: str | None = None
        current_rule_lines: list[str] = []
        in_contents = False

        glossary_term: str | None = None
        glossary_lines: list[str] = []

        for line in lines:
            stripped = line.strip()

            # Detect Contents section for section index
            if stripped == "Contents":
                in_contents = True
                continue

            if in_contents:
                if stripped == "":
                    continue
                # Section headers: "1. Game Concepts", "7. Additional Rules"
                section_match = _SECTION_HEADER_RE.match(stripped)
                if section_match:
                    sections[section_match.group(1)] = section_match.group(2)
                    continue
                # End of contents: hit a numbered rule (fall through to process)
                if _RULE_NUMBER_RE.match(stripped):
                    in_contents = False
                    # Fall through to process this line as a rule
                else:
                    # Skip non-section, non-rule lines in TOC (e.g. "Glossary", "Credits")
                    continue

            # Detect transition to glossary
            if stripped == "Glossary" and state != "glossary":
                # Flush current rule
                if current_rule_number is not None:
                    rules[current_rule_number] = Rule(
                        number=current_rule_number,
                        text=" ".join(current_rule_lines),
                    )
                state = "glossary"
                continue

            # Detect end of glossary (final Credits section)
            if state == "glossary" and stripped == "Credits":
                # Flush last glossary entry
                if glossary_term is not None:
                    glossary[glossary_term.lower()] = GlossaryEntry(
                        term=glossary_term,
                        definition=" ".join(glossary_lines).strip(),
                    )
                break

            # --- Rules parsing ---
            if state != "glossary":
                rule_match = _RULE_NUMBER_RE.match(stripped)
                if rule_match:
                    # Flush previous rule
                    if current_rule_number is not None:
                        rules[current_rule_number] = Rule(
                            number=current_rule_number,
                            text=" ".join(current_rule_lines),
                        )
                    current_rule_number = rule_match.group(1)
                    # Text after the rule number
                    rest = stripped[rule_match.end() :].strip()
                    current_rule_lines = [rest] if rest else []
                    state = "rules"
                elif state == "rules" and stripped and current_rule_number is not None:
                    # Continuation line for current rule
                    current_rule_lines.append(stripped)
                continue

            # --- Glossary parsing ---
            if state == "glossary":
                if stripped == "":
                    # Blank line separates glossary entries
                    if glossary_term is not None and glossary_lines:
                        glossary[glossary_term.lower()] = GlossaryEntry(
                            term=glossary_term,
                            definition=" ".join(glossary_lines).strip(),
                        )
                        glossary_term = None
                        glossary_lines = []
                elif glossary_term is None:
                    # This line is a new term
                    glossary_term = stripped
                    glossary_lines = []
                else:
                    # Definition continuation
                    glossary_lines.append(stripped)

        # Build subrule hierarchy: "704.5a" is a subrule of "704.5"
        for number, rule in rules.items():
            parent_number = _parent_rule_number(number)
            if parent_number and parent_number in rules:
                rules[parent_number].subrules.append(rule)

        # Sanity check: a valid Comprehensive Rules file should produce many rules
        if not rules:
            raise RulesError(
                f"Parse produced no rules from {len(lines)} lines — "
                "the rules file format may have changed"
            )

        # Assign parsed data
        self._rules = rules
        self._glossary = glossary
        self._sections = sections


def _parent_rule_number(number: str) -> str | None:
    """Return the parent rule number, or None if this is a top-level rule.

    ``"704.5k"`` -> ``"704.5"``, ``"704.5"`` -> ``"704"``, ``"704"`` -> ``None``.
    """
    if "." not in number:
        return None
    return number[:-1] if number[-1].isalpha() else number.split(".")[0]


_KEYWORD_RULE_RE = re.compile(r"\brule 702\.")


def _is_keyword_glossary_entry(entry: GlossaryEntry) -> bool:
    """Check if a glossary entry references a 702.x rule (keyword ability)."""
    return bool(_KEYWORD_RULE_RE.search(entry.definition))
