"""Scryfall MCP provider — card search, lookup, rulings, and set info."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan
from fastmcp.tools import ToolResult
from pydantic import Field

from mtg_mcp_server.config import Settings
from mtg_mcp_server.providers import (
    ATTRIBUTION_SCRYFALL,
    TAGS_LOOKUP,
    TAGS_SEARCH,
    TOOL_ANNOTATIONS,
    format_legalities,
)
from mtg_mcp_server.services.scryfall import CardNotFoundError, ScryfallClient, ScryfallError
from mtg_mcp_server.utils.formatters import (
    ResponseFormatParam,
    format_card_detail,
    format_card_line,
)
from mtg_mcp_server.utils.slim import slim_card

# Module-level client set by the lifespan and read through _get_client().
# Kept over ctx.lifespan_context so tests can patch it and other servers can
# reuse the client.
_client: ScryfallClient | None = None


@lifespan
async def scryfall_lifespan(server: FastMCP):
    """Manage the ScryfallClient lifecycle.

    Create the client once at startup using settings (honoring env var overrides),
    keep the httpx connection pool open for the server's lifetime, then tear down.
    """
    global _client
    settings = Settings()
    client = ScryfallClient(base_url=settings.scryfall_base_url)
    async with client:
        _client = client
        yield {}
    _client = None


scryfall_mcp = FastMCP("Scryfall", lifespan=scryfall_lifespan, mask_error_details=True)


def _get_client() -> ScryfallClient:
    """Return the initialized client or raise if the lifespan hasn't started."""
    if _client is None:
        raise RuntimeError("ScryfallClient not initialized — server lifespan not running")
    return _client


@scryfall_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_SEARCH)
async def search_cards(
    query: Annotated[
        str,
        Field(
            description="Scryfall search query (e.g. 'f:commander id:sultai t:creature cmc<=3'). See scryfall.com/docs/syntax"
        ),
    ],
    page: Annotated[int, Field(description="Page number for paginated results, 1-indexed")] = 1,
    limit: Annotated[
        int,
        Field(description="Max cards to return (default 30, 0 for all)"),
    ] = 30,
    response_format: ResponseFormatParam = "detailed",
) -> ToolResult:
    """Search for Magic cards using Scryfall syntax.

    Examples: "f:commander id:sultai t:creature", "o:destroy t:instant cmc<=3"
    See https://scryfall.com/docs/syntax for full syntax reference.
    """
    if limit < 0:
        raise ToolError(f"limit must be >= 0 (0 for all), got {limit}")

    client = _get_client()
    try:
        result = await client.search_cards(query, page=page)
    except CardNotFoundError as exc:
        raise ToolError(f"No cards found for query: '{query}'. Check your search syntax.") from exc
    except ScryfallError as exc:
        raise ToolError(f"Scryfall API error: {exc}") from exc

    cards = result.data if limit == 0 else result.data[:limit]
    showing = len(cards)
    total = len(result.data)

    lines = [f"Found {result.total_cards} cards (showing {showing} of {total}, page {page}):"]
    for card in cards:
        lines.append(format_card_line(card, response_format=response_format))
    if showing < total:
        lines.append(f"\n{total - showing} more on this page — increase limit to see them.")
    if result.has_more:
        lines.append(f"More results available — use page={page + 1}")
    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_SCRYFALL,
        structured_content={
            "query": query,
            "total_cards": result.total_cards,
            "page": page,
            "has_more": result.has_more,
            "showing": showing,
            "cards": [slim_card(card) for card in cards],
        },
    )


@scryfall_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_LOOKUP)
async def card_details(
    name: Annotated[
        str,
        Field(description="Card name — exact match by default (e.g. 'Muldrotha, the Gravetide')"),
    ],
    fuzzy: Annotated[
        bool,
        Field(
            description="Use fuzzy matching for approximate names (e.g. 'muldrotha' finds 'Muldrotha, the Gravetide')"
        ),
    ] = False,
    response_format: ResponseFormatParam = "detailed",
) -> ToolResult:
    """Get full details for a Magic card by exact or fuzzy name."""
    client = _get_client()
    try:
        card = await client.get_card_by_name(name, fuzzy=fuzzy)
    except CardNotFoundError as exc:
        raise ToolError(f"Card not found: '{name}'. Check spelling or try fuzzy=true.") from exc
    except ScryfallError as exc:
        raise ToolError(f"Scryfall API error: {exc}") from exc

    lines = format_card_detail(card, response_format=response_format)
    if response_format == "detailed":
        lines.append(f"Legalities: {format_legalities(card.legalities)}")
        lines.append(f"Scryfall: {card.scryfall_uri}")
    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_SCRYFALL,
        structured_content=card.model_dump(mode="json"),
    )


@scryfall_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_LOOKUP)
async def card_rulings(
    name: Annotated[str, Field(description="Card name to get official rulings for (exact match)")],
) -> ToolResult:
    """Get official rulings and clarifications for a Magic card."""
    client = _get_client()
    try:
        card = await client.get_card_by_name(name)
        rulings = await client.get_rulings(card.id)
    except CardNotFoundError as exc:
        raise ToolError(f"Card not found: '{name}'. Check spelling.") from exc
    except ScryfallError as exc:
        raise ToolError(f"Scryfall API error: {exc}") from exc

    rulings_data = [r.model_dump(mode="json") for r in rulings]
    if not rulings:
        return ToolResult(
            content=f"**{card.name}** — No rulings available." + ATTRIBUTION_SCRYFALL,
            structured_content={"name": card.name, "total_rulings": 0, "rulings": []},
        )

    lines = [f"**{card.name}** — {len(rulings)} ruling(s):"]
    for ruling in rulings:
        lines.append(f"  [{ruling.published_at}] {ruling.comment}")
    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_SCRYFALL,
        structured_content={
            "name": card.name,
            "total_rulings": len(rulings),
            "rulings": rulings_data,
        },
    )


@scryfall_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_LOOKUP)
async def set_info(
    set_code: Annotated[
        str,
        Field(description="Set code (e.g. 'dom', 'mh2', 'lci')"),
    ],
) -> ToolResult:
    """Get metadata for a Magic set by its code."""
    client = _get_client()
    try:
        info = await client.get_set(set_code)
    except CardNotFoundError as exc:
        raise ToolError(f"Set not found: '{set_code}'. Check the set code.") from exc
    except ScryfallError as exc:
        raise ToolError(f"Scryfall API error: {exc}") from exc

    lines = [
        f"**{info.name}** ({info.code.upper()})",
        f"Type: {info.set_type}",
    ]
    if info.released_at:
        lines.append(f"Released: {info.released_at}")
    lines.append(f"Card count: {info.card_count}")
    if info.digital:
        lines.append("Digital-only set")
    if info.scryfall_uri:
        lines.append(f"Scryfall: {info.scryfall_uri}")
    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_SCRYFALL,
        structured_content=info.model_dump(mode="json"),
    )
