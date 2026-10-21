"""Scryfall bulk data MCP provider -- rate-limit-free card lookup and search.

Uses Scryfall's Oracle Cards bulk file for rate-limit-free in-memory card data
including prices, legalities, and EDHREC rank.
"""

from __future__ import annotations

import contextlib
import sys
from typing import TYPE_CHECKING, Annotated, Literal

import structlog
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan
from fastmcp.tools import ToolResult
from pydantic import Field

from mtg_mcp_server.config import Settings
from mtg_mcp_server.providers import (
    ATTRIBUTION_SCRYFALL_BULK,
    TAGS_ALL_FORMATS,
    TAGS_LOOKUP,
    TAGS_SEARCH,
    TAGS_VALIDATE,
    TOOL_ANNOTATIONS,
    format_legalities,
)
from mtg_mcp_server.services.scryfall_bulk import (
    ScryfallBulkClient,
    ScryfallBulkError,
    filter_card_pool,
)
from mtg_mcp_server.utils.color_identity import parse_color_identity
from mtg_mcp_server.utils.format_rules import get_format_rules, normalize_format
from mtg_mcp_server.utils.formatters import (
    ResponseFormat,
    ResponseFormatParam,
    format_card_detail,
)
from mtg_mcp_server.utils.query_parser import parse_query
from mtg_mcp_server.utils.slim import slim_card

if TYPE_CHECKING:
    from mtg_mcp_server.types import Card

# Module-level client set by the lifespan. See scryfall.py for pattern rationale.
_client: ScryfallBulkClient | None = None


@lifespan
async def scryfall_bulk_lifespan(server: FastMCP):
    """Initialize the ScryfallBulkClient and start its background refresh timer.

    Data is loaded lazily on the first tool call, not during startup. The
    background task periodically re-downloads data at the configured interval.
    """
    global _client
    settings = Settings()
    client = ScryfallBulkClient(
        base_url=settings.scryfall_base_url,
        refresh_hours=settings.bulk_data_refresh_hours,
    )
    async with client:
        _client = client
        client.start_background_refresh()
        yield {}
    _client = None


scryfall_bulk_mcp = FastMCP(
    "Scryfall Bulk Data", lifespan=scryfall_bulk_lifespan, mask_error_details=True
)

log = structlog.get_logger(provider="scryfall_bulk")


def _get_client() -> ScryfallBulkClient:
    """Return the initialized client or raise if the lifespan hasn't started."""
    if _client is None:
        raise RuntimeError("ScryfallBulkClient not initialized -- server lifespan not running")
    return _client


def _format_card_detail_with_legalities(
    card: Card, *, response_format: ResponseFormat = "detailed"
) -> list[str]:
    """Build card detail lines with legalities appended.

    Uses the shared ``format_card_detail`` helper for core fields, then
    appends legalities (detailed mode only).
    """
    lines = format_card_detail(card, response_format=response_format)
    if response_format == "detailed":
        lines.append(f"Legalities: {format_legalities(card.legalities)}")
    return lines


def _score_similarity(source: Card, candidate: Card) -> float:
    """Score how similar a candidate card is to a source card."""
    source_keywords = {k.lower() for k in source.keywords}
    source_type_words = {
        w.lower() for w in source.type_line.replace("\u2014", " ").split() if len(w) > 2
    }
    source_text_words: set[str] = set()
    if source.oracle_text:
        source_text_words = {
            w.lower()
            for w in source.oracle_text.replace(",", " ").replace(".", " ").split()
            if len(w) > 4
        }

    score = 0.0
    if candidate.keywords:
        card_keywords = {k.lower() for k in candidate.keywords}
        score += len(source_keywords & card_keywords) * 2.0
    card_type_words = {
        w.lower() for w in candidate.type_line.replace("\u2014", " ").split() if len(w) > 2
    }
    score += len(source_type_words & card_type_words) * 1.5
    if abs(candidate.cmc - source.cmc) <= 1:
        score += 1.0
    if candidate.oracle_text and source_text_words:
        card_text_words = {
            w.lower()
            for w in candidate.oracle_text.replace(",", " ").replace(".", " ").split()
            if len(w) > 4
        }
        score += len(source_text_words & card_text_words) * 1.0
    return score


@scryfall_bulk_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_LOOKUP)
async def card_lookup(
    name: Annotated[
        str,
        Field(description="Card name for exact lookup, case-insensitive (e.g. 'Sol Ring')"),
    ],
    response_format: ResponseFormatParam = "detailed",
) -> ToolResult:
    """Look up a Magic card by exact name using Scryfall bulk data.

    Returns full card details including mana cost, type, oracle text,
    colors, power/toughness, prices, legalities, and EDHREC rank.
    Case-insensitive.
    """
    client = _get_client()
    try:
        card = await client.get_card(name)
    except ScryfallBulkError as exc:
        raise ToolError(f"Scryfall bulk data error: {exc}") from exc

    if card is None:
        raise ToolError(f"Card not found: '{name}'. Check spelling.")

    return ToolResult(
        content="\n".join(
            _format_card_detail_with_legalities(card, response_format=response_format)
        )
        + ATTRIBUTION_SCRYFALL_BULK,
        structured_content=card.model_dump(mode="json"),
    )


@scryfall_bulk_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_SEARCH)
async def card_search(
    query: Annotated[str, Field(description="Substring to search for, case-insensitive")],
    search_field: Annotated[
        Literal["name", "type", "text"],
        Field(
            description="Field to search in -- 'name' (card name), 'type' (type line), or 'text' (oracle text)"
        ),
    ] = "name",
    limit: Annotated[int, Field(description="Maximum number of results to return")] = 20,
    response_format: ResponseFormatParam = "detailed",
) -> ToolResult:
    """Search for Magic cards in Scryfall bulk data.

    Args:
        query: Substring to search for (case-insensitive).
        search_field: Field to search in -- "name", "type", or "text".
        limit: Maximum number of results to return (default 20).
    """
    client = _get_client()

    try:
        if search_field == "name":
            results = await client.search_cards(query, limit=limit)
        elif search_field == "type":
            results = await client.search_by_type(query, limit=limit)
        else:  # search_field == "text"
            results = await client.search_by_text(query, limit=limit)
    except ScryfallBulkError as exc:
        raise ToolError(f"Scryfall bulk data error: {exc}") from exc

    if not results:
        raise ToolError(f"No cards found for {search_field} search: '{query}'.")

    lines = [f"Found {len(results)} card(s) matching {search_field}='{query}':"]
    for card in results:
        if response_format == "concise":
            cost = f" {card.mana_cost}" if card.mana_cost else ""
            lines.append(f"  {card.name}{cost}")
        else:
            cost = f" {card.mana_cost}" if card.mana_cost else ""
            lines.append(f"  {card.name}{cost} -- {card.type_line}")
    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_SCRYFALL_BULK,
        structured_content={
            "query": query,
            "search_field": search_field,
            "total_results": len(results),
            "cards": [slim_card(card) for card in results],
        },
    )


# ---------------------------------------------------------------------------
# Cross-format tools
# ---------------------------------------------------------------------------


@scryfall_bulk_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_VALIDATE)
async def format_legality(
    cards: Annotated[
        list[str],
        Field(description="List of card names to check legality for"),
    ],
    format: Annotated[
        str,
        Field(description="Format to check (e.g. 'commander', 'modern', 'standard', 'legacy')"),
    ],
) -> ToolResult:
    """Batch legality check for cards in a specific format.

    Returns a markdown table showing the legality status of each card
    in the specified format. Handles common format aliases (e.g. 'edh'
    for 'commander').
    """
    if not cards:
        raise ToolError("Provide at least one card name to check.")

    client = _get_client()
    fmt = normalize_format(format, strict=False)

    try:
        resolved = await client.get_cards(cards)
    except ScryfallBulkError as exc:
        raise ToolError(f"Scryfall bulk data error: {exc}") from exc

    lines = [f"## Legality Check: {fmt.title()}", "", "| Card | Status |", "|------|--------|"]
    cards_data = []

    for name in cards:
        card = resolved.get(name)
        if card is None:
            lines.append(f"| {name} | Not Found |")
            cards_data.append({"name": name, "status": "not_found"})
        else:
            status = card.legalities.get(fmt, "unknown")
            display_status = status.replace("_", " ").title()
            lines.append(f"| {card.name} | {display_status} |")
            cards_data.append({"name": card.name, "status": status})

    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_SCRYFALL_BULK,
        structured_content={
            "format": fmt,
            "total_cards": len(cards),
            "cards": cards_data,
        },
    )


@scryfall_bulk_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_SEARCH)
async def format_search(
    format: Annotated[
        str,
        Field(description="Format to search in (e.g. 'commander', 'modern', 'standard')"),
    ],
    query: Annotated[
        str,
        Field(
            description="Search query -- card name, type, or oracle text substring (e.g. 'flying creatures', 'destroy target')"
        ),
    ],
    color_identity: Annotated[
        str | None,
        Field(
            description="Color identity filter (e.g. 'sultai', 'WU', 'red'). Only returns cards within this identity."
        ),
    ] = None,
    max_price: Annotated[
        float | None,
        Field(description="Maximum USD price filter"),
    ] = None,
    rarity: Annotated[
        str | None,
        Field(description="Rarity filter (e.g. 'common', 'uncommon', 'rare', 'mythic')"),
    ] = None,
    limit: Annotated[int, Field(description="Maximum results to return")] = 20,
    response_format: ResponseFormatParam = "detailed",
) -> ToolResult:
    """Search for legal cards in a specific format using natural language.

    Combines format legality filtering with name/type/text search and
    optional color identity, price, and rarity constraints. Results are
    sorted by EDHREC rank (most popular first).
    """
    if not query.strip():
        raise ToolError("Provide a search query.")

    client = _get_client()
    fmt = normalize_format(format, strict=False)
    try:
        identity = parse_color_identity(color_identity) if color_identity else None
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    try:
        all_cards = await client.all_cards()
    except ScryfallBulkError as exc:
        raise ToolError(f"Scryfall bulk data error: {exc}") from exc

    # Parse natural language into structured filters
    parsed = parse_query(query)

    matches = filter_card_pool(
        all_cards,
        format=fmt,
        color_identity=identity,
        type_contains=list(parsed.type_contains),
        text_any=list(parsed.text_any),
        cmc_eq=parsed.cmc_eq,
        max_price=max_price,
        rarity=rarity.lower() if rarity else None,
        limit=sys.maxsize,
    )
    # Free-text terms may match the name or type line as well as oracle text
    if parsed.text_contains:
        terms = [t.lower() for t in parsed.text_contains]
        matches = [
            c
            for c in matches
            if all(
                t in c.name.lower()
                or t in c.type_line.lower()
                or t in (c.oracle_text or "").lower()
                for t in terms
            )
        ]
    MAX_CANDIDATES = 5000  # Cap accumulation for very broad queries
    matches = matches[:MAX_CANDIDATES]

    if not matches:
        raise ToolError(
            f"No legal {fmt} cards found matching '{query}'"
            + (f" in {color_identity}" if color_identity else "")
            + "."
        )

    # Sort by EDHREC rank (lower = more popular), None last
    matches.sort(key=lambda c: (c.edhrec_rank is None, c.edhrec_rank or 0))
    matches = matches[:limit]

    desc = parsed.description or query
    lines = [f"## {fmt.title()} Cards: {desc}"]
    if color_identity:
        lines[0] += f" ({color_identity})"
    lines.append(f"Found {len(matches)} result(s):")
    lines.append("")
    for card in matches:
        if response_format == "concise":
            cost = f" {card.mana_cost}" if card.mana_cost else ""
            lines.append(f"  {card.name}{cost}")
        else:
            cost = f" {card.mana_cost}" if card.mana_cost else ""
            price = f" (${card.prices.usd})" if card.prices.usd else ""
            lines.append(f"  {card.name}{cost} -- {card.type_line}{price}")

    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_SCRYFALL_BULK,
        structured_content={
            "format": fmt,
            "query": query,
            "color_identity": color_identity,
            "total_results": len(matches),
            "cards": [slim_card(card) for card in matches],
        },
    )


# ---------------------------------------------------------------------------
# Format staples ranking helpers
# ---------------------------------------------------------------------------

_COMPETITIVE_KEYWORDS = frozenset({"flash", "haste", "hexproof", "cycling"})

_TYPE_SCORES: dict[str, float] = {
    "instant": -10.0,
    "sorcery": -8.0,
    "creature": -5.0,
    "enchantment": -3.0,
    "artifact": -2.0,
    "planeswalker": -4.0,
}

_RARITY_SCORES: dict[str, float] = {
    "mythic": 0.0,
    "rare": 2.0,
    "uncommon": 3.5,
    "common": 5.0,
}


def _score_competitive(card: Card) -> float:
    """Score a card for competitive (non-singleton) format relevance.

    Lower score = better card (matches EDHREC rank semantics where lower = more popular).
    Combines CMC efficiency, card type, rarity, market price, and keyword presence.
    """
    # CMC: lower is better in competitive (0-40 range)
    cmc_score = min(card.cmc * 8.0, 40.0)

    # Type: instants/sorceries score best in 60-card formats
    type_lower = card.type_line.lower()
    type_score = 0.0
    for type_key, bonus in _TYPE_SCORES.items():
        if type_key in type_lower:
            type_score = bonus
            break

    # Rarity: mild tiebreaker — secondary to CMC, type, and price
    rarity_score = _RARITY_SCORES.get(card.rarity, 10.0)

    # Price as demand proxy: higher price → lower score
    price_score = 0.0
    if card.prices and card.prices.usd:
        with contextlib.suppress(ValueError, TypeError):
            price_score = max(-15.0, -float(card.prices.usd) * 1.5)

    # Competitive keyword bonus
    keyword_score = 0.0
    if card.keywords:
        keyword_score = sum(-3.0 for k in card.keywords if k.lower() in _COMPETITIVE_KEYWORDS)

    return cmc_score + type_score + rarity_score + price_score + keyword_score


def _is_singleton_format(fmt: str) -> bool:
    """Check if a format uses singleton deck construction rules."""
    try:
        return get_format_rules(fmt).singleton
    except KeyError:
        log.debug("singleton_check.unknown_format", format=fmt)
        return False


@scryfall_bulk_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_SEARCH)
async def format_staples(
    format: Annotated[
        str,
        Field(description="Format to find staples for (e.g. 'commander', 'modern', 'legacy')"),
    ],
    color: Annotated[
        str | None,
        Field(
            description="Color identity filter (e.g. 'sultai', 'WU', 'red'). Only returns cards within this identity."
        ),
    ] = None,
    card_type: Annotated[
        str | None,
        Field(description="Card type filter (e.g. 'creature', 'instant', 'land')"),
    ] = None,
    limit: Annotated[int, Field(description="Maximum results to return")] = 20,
    ranking_mode: Annotated[
        Literal["auto", "edhrec", "competitive"],
        Field(
            description=(
                "How to rank staples: 'auto' (default) uses 'edhrec' for singleton formats "
                "and 'competitive' otherwise, 'edhrec' uses Commander popularity, "
                "'competitive' uses a mana-efficiency heuristic."
            )
        ),
    ] = "auto",
    response_format: ResponseFormatParam = "detailed",
) -> ToolResult:
    """Find the most popular (staple) cards legal in a format.

    Ranking adapts to the format: singleton formats (Commander, Brawl, Oathbreaker)
    use EDHREC rank; other formats use a mana-efficiency heuristic.
    """
    client = _get_client()
    fmt = normalize_format(format, strict=False)
    use_edhrec = ranking_mode == "edhrec" or (ranking_mode == "auto" and _is_singleton_format(fmt))

    try:
        identity = parse_color_identity(color) if color else None
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    try:
        all_cards = await client.all_cards()
    except ScryfallBulkError as exc:
        raise ToolError(f"Scryfall bulk data error: {exc}") from exc

    matches = filter_card_pool(
        all_cards,
        format=fmt,
        color_identity=identity,
        type_contains=[card_type] if card_type else None,
        limit=sys.maxsize,
    )
    # EDHREC mode excludes cards without rank; competitive does not
    if use_edhrec:
        matches = [c for c in matches if c.edhrec_rank is not None]

    if not matches:
        raise ToolError(f"No staples found for {fmt}" + (f" ({color})" if color else "") + ".")

    if use_edhrec:
        matches.sort(key=lambda c: c.edhrec_rank or 0)
        matches = matches[:limit]
        scored: list[tuple[float, Card]] | None = None
    else:
        scored = sorted(
            ((_score_competitive(card), card) for card in matches),
            key=lambda t: t[0],
        )[:limit]
        matches = [card for _, card in scored]

    lines = [f"## {fmt.title()} Staples"]
    if color:
        lines[0] += f" ({color})"
    if card_type:
        lines[0] += f" -- {card_type.title()}"
    lines.append("")

    if response_format == "concise":
        if scored is None:
            for card in matches:
                lines.append(f"  {card.name} (rank: {card.edhrec_rank})")
        else:
            for score, card in scored:
                lines.append(f"  {card.name} (score: {score:.1f})")
    else:
        if scored is None:
            lines.append("| Rank | Card | Mana Cost | Type |")
            lines.append("|------|------|-----------|------|")
            for card in matches:
                cost = card.mana_cost or ""
                lines.append(f"| #{card.edhrec_rank} | {card.name} | {cost} | {card.type_line} |")
        else:
            lines.append("| Score | Card | Mana Cost | Type |")
            lines.append("|-------|------|-----------|------|")
            for score, card in scored:
                cost = card.mana_cost or ""
                lines.append(f"| {score:.1f} | {card.name} | {cost} | {card.type_line} |")

    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_SCRYFALL_BULK,
        structured_content={
            "format": fmt,
            "color": color,
            "card_type": card_type,
            "ranking_mode": "edhrec" if use_edhrec else "competitive",
            "total_results": len(matches),
            "cards": [slim_card(card) for card in matches],
        },
    )


@scryfall_bulk_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_SEARCH)
async def similar_cards(
    card_name: Annotated[
        str,
        Field(description="Name of the card to find similar cards for"),
    ],
    format: Annotated[
        str | None,
        Field(description="Format filter (e.g. 'commander', 'modern'). Only returns legal cards."),
    ] = None,
    max_price: Annotated[
        float | None,
        Field(description="Maximum USD price filter"),
    ] = None,
    limit: Annotated[int, Field(description="Maximum results to return")] = 10,
    response_format: ResponseFormatParam = "detailed",
) -> ToolResult:
    """Find cards similar to a given card.

    Scores similarity based on shared keywords, type words, CMC
    proximity, and oracle text overlap. Optionally filter by format
    legality and price.
    """
    client = _get_client()

    try:
        source = await client.get_card(card_name)
        all_cards = await client.all_cards()
    except ScryfallBulkError as exc:
        raise ToolError(f"Scryfall bulk data error: {exc}") from exc

    if source is None:
        raise ToolError(f"Card not found: '{card_name}'. Check spelling.")

    fmt = normalize_format(format, strict=False) if format else None

    scored: list[tuple[float, Card]] = []
    source_name_lower = source.name.lower()

    pool = filter_card_pool(all_cards, format=fmt or None, max_price=max_price, limit=sys.maxsize)
    for card in pool:
        if card.name.lower() == source_name_lower:
            continue
        score = _score_similarity(source, card)
        if score > 0:
            scored.append((score, card))

    if not scored:
        raise ToolError(f"No similar cards found for '{source.name}'.")

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]

    lines = [
        f"## Cards Similar to {source.name}",
        f"*{source.mana_cost or 'No cost'} -- {source.type_line}*",
        "",
    ]
    for score, card in top:
        if response_format == "concise":
            lines.append(f"  {card.name} (score: {score:.0f}%)")
        else:
            cost = f" {card.mana_cost}" if card.mana_cost else ""
            price = f" (${card.prices.usd})" if card.prices.usd else ""
            lines.append(f"  {card.name}{cost} -- {card.type_line}{price} [score: {score:.1f}]")

    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_SCRYFALL_BULK,
        structured_content={
            "source_card": source.name,
            "total_results": len(top),
            "similar": [{"score": score, **slim_card(card)} for score, card in top],
        },
    )


@scryfall_bulk_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_LOOKUP)
async def random_card(
    format: Annotated[
        str | None,
        Field(description="Format filter (e.g. 'commander', 'modern'). Only returns legal cards."),
    ] = None,
    color_identity: Annotated[
        str | None,
        Field(
            description="Color identity filter (e.g. 'sultai', 'WU', 'red'). Only returns cards within this identity."
        ),
    ] = None,
    card_type: Annotated[
        str | None,
        Field(description="Card type filter (e.g. 'creature', 'instant', 'land')"),
    ] = None,
    rarity: Annotated[
        str | None,
        Field(description="Rarity filter (e.g. 'common', 'uncommon', 'rare', 'mythic')"),
    ] = None,
) -> ToolResult:
    """Get a random Magic card, optionally filtered by format, color, type, and rarity.

    Returns full card details in the same format as card_lookup.
    """
    client = _get_client()
    fmt = normalize_format(format, strict=False) if format else None
    try:
        identity = parse_color_identity(color_identity) if color_identity else None
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    try:
        card = await client.random_card(
            format=fmt,
            color_identity=identity,
            type_contains=card_type,
            rarity=rarity.lower() if rarity else None,
        )
    except ScryfallBulkError as exc:
        raise ToolError(f"Scryfall bulk data error: {exc}") from exc

    if card is None:
        raise ToolError("No cards match the specified filters.")

    return ToolResult(
        content="\n".join(_format_card_detail_with_legalities(card)) + ATTRIBUTION_SCRYFALL_BULK,
        structured_content=card.model_dump(mode="json"),
    )


@scryfall_bulk_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_ALL_FORMATS)
async def ban_list(
    format: Annotated[
        str,
        Field(description="Format to check ban list for (e.g. 'commander', 'modern', 'standard')"),
    ],
) -> ToolResult:
    """Get the banned and restricted cards for a format.

    Returns alphabetically sorted lists of banned and restricted cards,
    including their type lines.
    """
    if not format.strip():
        raise ToolError("Provide a format name.")

    client = _get_client()
    fmt = normalize_format(format, strict=False)

    try:
        banned = await client.cards_by_legality(fmt, "banned")
        restricted = await client.cards_by_legality(fmt, "restricted")
    except ScryfallBulkError as exc:
        raise ToolError(f"Scryfall bulk data error: {exc}") from exc

    banned.sort(key=lambda c: c.name)
    restricted.sort(key=lambda c: c.name)

    lines = [f"## {fmt.title()} Ban List"]

    if banned:
        lines.append("")
        lines.append(f"### Banned ({len(banned)} cards)")
        lines.append("")
        for card in banned:
            lines.append(f"  - **{card.name}** -- {card.type_line}")
    else:
        lines.append("")
        lines.append("No banned cards in this format.")

    if restricted:
        lines.append("")
        lines.append(f"### Restricted ({len(restricted)} cards)")
        lines.append("")
        for card in restricted:
            lines.append(f"  - **{card.name}** -- {card.type_line}")

    if not banned and not restricted:
        lines[-1] = "No banned or restricted cards in this format."

    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_SCRYFALL_BULK,
        structured_content={
            "format": fmt,
            "banned": [{"name": c.name, "type_line": c.type_line} for c in banned],
            "restricted": [{"name": c.name, "type_line": c.type_line} for c in restricted],
        },
    )
