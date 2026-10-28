"""TopDeck.gg MCP provider: tournament results, standings, decklists and metagame.

Needs a free API key (``MTG_MCP_TOPDECK_API_KEY``). The orchestrator mounts
this provider only when the key is set.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated

import structlog
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan
from fastmcp.tools import ToolResult
from pydantic import Field

from mtg_mcp_server.config import Settings
from mtg_mcp_server.providers import ATTRIBUTION_TOPDECK, TAGS_CONSTRUCTED, TOOL_ANNOTATIONS
from mtg_mcp_server.services.topdeck import TopDeckClient, TopDeckError, TournamentNotFoundError

if TYPE_CHECKING:
    from mtg_mcp_server.types import TopDeckTournament

log = structlog.get_logger(service="topdeck")

# Module-level client set by the lifespan. See scryfall.py for pattern rationale.
_client: TopDeckClient | None = None


@lifespan
async def topdeck_lifespan(server: FastMCP):
    """Manage the TopDeckClient lifecycle. Without an API key, no client is created."""
    global _client
    settings = Settings()
    key = settings.topdeck_api_key.get_secret_value() if settings.topdeck_api_key else ""
    if not key:
        log.warning("topdeck_api_key_missing", setting="MTG_MCP_TOPDECK_API_KEY")
        yield {}
        return
    client = TopDeckClient(base_url=settings.topdeck_base_url, api_key=key)
    async with client:
        _client = client
        yield {}
    _client = None


topdeck_mcp = FastMCP("TopDeck", lifespan=topdeck_lifespan, mask_error_details=True)


def _get_client() -> TopDeckClient:
    """Return the initialized client or raise if the lifespan hasn't started."""
    if _client is None:
        raise RuntimeError(
            "TopDeckClient not initialized: set MTG_MCP_TOPDECK_API_KEY and restart the server"
        )
    return _client


def _tool_error(exc: TopDeckError) -> ToolError:
    """Turn a service error into an actionable tool error."""
    if exc.status_code == 401:
        return ToolError("TopDeck.gg rejected the API key. Check MTG_MCP_TOPDECK_API_KEY.")
    if exc.status_code == 429:
        return ToolError("TopDeck.gg rate limit reached. Try again in a minute.")
    if exc.status_code is None:
        return ToolError(exc.message)
    return ToolError(f"TopDeck.gg API error: {exc}")


def _date(timestamp: int) -> str:
    """Format a Unix timestamp as an ISO date (UTC)."""
    return datetime.fromtimestamp(timestamp, UTC).date().isoformat()


def _place(t: TopDeckTournament) -> str | None:
    """City and state, or the organizer's address string."""
    parts = [p for p in (t.location.city, t.location.state) if p]
    return ", ".join(parts) or t.location.address


def _pct(part: int, whole: int) -> float | None:
    """Percentage rounded to 1 decimal, or None when the whole is 0."""
    return round(100 * part / whole, 1) if whole else None


def _show_pct(value: object) -> str:
    return f"{value}%" if value is not None else "n/a"


FormatParam = Annotated[
    str,
    Field(
        description=(
            "Magic format as TopDeck.gg names it, case-insensitive: e.g. 'EDH', 'Modern', "
            "'Pauper', 'Legacy', 'Duel Commander'. 'EDH' is competitive Commander (cEDH); "
            "'Casual EDH' is separate."
        )
    ),
]
DaysParam = Annotated[int, Field(ge=1, le=90, description="How many days back to search")]
MinPlayersParam = Annotated[
    int, Field(ge=2, description="Only include tournaments with at least this many players")
]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@topdeck_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_CONSTRUCTED)
async def search_tournaments(
    format: FormatParam,
    days: DaysParam = 30,
    min_players: MinPlayersParam = 16,
    limit: Annotated[int, Field(ge=1, le=50, description="Maximum tournaments to list")] = 20,
) -> ToolResult:
    """List recent completed TopDeck.gg tournaments in a format, newest first.

    Each entry has the date, player count, top-cut size, place, tournament ID,
    and the winner with their commander or archetype. Pass the tournament ID
    to `topdeck_tournament` for full standings.
    """
    client = _get_client()
    try:
        tournaments = await client.search_tournaments(format, days=days, min_players=min_players)
    except TopDeckError as exc:
        raise _tool_error(exc) from exc

    shown = tournaments[:limit]
    rows: list[dict[str, object]] = []
    lines: list[str] = []
    if not shown:
        lines.append(
            f"No {format} tournaments with {min_players}+ players in the last {days} days."
        )
    else:
        lines.append(
            f"**{len(tournaments)} {shown[0].format} tournament(s)** in the last {days} days "
            f"({min_players}+ players)"
        )
        if len(tournaments) > len(shown):
            lines.append(f"Showing the newest {len(shown)}.")
        lines.append("")
    for t in shown:
        winner = t.standings[0] if t.standings else None
        place = _place(t)
        details = [_date(t.start_date), f"{len(t.standings)} players"]
        if t.top_cut:
            details.append(f"top {t.top_cut}")
        if place:
            details.append(place)
        lines.append(f"- **{t.name}** (`{t.tid}`): {', '.join(details)}")
        if winner:
            deck = f" ({winner.deck})" if winner.deck else ""
            lines.append(f"  Winner: {winner.name}{deck}")
        rows.append(
            {
                "tid": t.tid,
                "name": t.name,
                "date": _date(t.start_date),
                "players": len(t.standings),
                "top_cut": t.top_cut,
                "place": place,
                "winner": winner.name if winner else None,
                "winner_deck": winner.deck if winner else None,
            }
        )

    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_TOPDECK,
        structured_content={
            "format": format,
            "days": days,
            "min_players": min_players,
            "total": len(tournaments),
            "tournaments": rows,
        },
    )


@topdeck_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_CONSTRUCTED)
async def tournament(
    tid: Annotated[
        str,
        Field(description="TopDeck.gg tournament ID, as listed by `topdeck_search_tournaments`"),
    ],
    top: Annotated[int, Field(ge=1, le=100, description="Number of standings rows to show")] = 16,
) -> ToolResult:
    """Show a completed TopDeck.gg tournament's details and top standings.

    Each row has the rank, player name and ID, match record (W-D-L) and the
    player's commander or archetype. Pass the tournament and player IDs to
    `topdeck_player_deck` for the decklist.
    """
    client = _get_client()
    try:
        t = await client.get_tournament(tid)
    except TournamentNotFoundError as exc:
        raise ToolError(
            f"TopDeck.gg tournament not found or not finished: '{tid}'. "
            "Use `topdeck_search_tournaments` to find completed tournaments."
        ) from exc
    except TopDeckError as exc:
        raise _tool_error(exc) from exc

    place = _place(t)
    lines = [f"**{t.name}** ({t.format})"]
    details = [f"Date: {_date(t.start_date)}", f"Players: {len(t.standings)}"]
    if t.swiss_rounds:
        details.append(f"Swiss rounds: {t.swiss_rounds}")
    details.append(f"Top cut: {t.top_cut or 'none'}")
    lines.append(" | ".join(details))
    if place:
        lines.append(f"Location: {place}")
    lines.append("")
    lines.append(f"### Top {min(top, len(t.standings))} (record W-D-L)")
    rows: list[dict[str, object]] = []
    for rank, s in enumerate(t.standings[:top], start=1):
        deck = f": {s.deck}" if s.deck else ""
        lines.append(f"{rank}. {s.name} (`{s.id}`), {s.wins}-{s.draws}-{s.losses}{deck}")
        rows.append({"rank": rank, **s.model_dump(mode="json"), "deck": s.deck})

    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_TOPDECK,
        structured_content={
            **t.model_dump(mode="json", exclude={"standings"}),
            "players": len(t.standings),
            "standings": rows,
        },
    )


@topdeck_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_CONSTRUCTED)
async def player_deck(
    tid: Annotated[str, Field(description="TopDeck.gg tournament ID")],
    player_id: Annotated[
        str, Field(description="Player ID from the tournament's standings (`topdeck_tournament`)")
    ],
) -> ToolResult:
    """Fetch a player's record and decklist from one TopDeck.gg tournament.

    Decklists are public once the tournament has ended, or earlier when the
    organizer shows decks.
    """
    client = _get_client()
    try:
        player = await client.get_player(tid, player_id)
    except TournamentNotFoundError as exc:
        raise ToolError(
            f"Player '{player_id}' not found in TopDeck.gg tournament '{tid}'. "
            "Check the IDs with `topdeck_tournament`."
        ) from exc
    except TopDeckError as exc:
        raise _tool_error(exc) from exc

    standing = f", standing {player.standing}" if player.standing is not None else ""
    lines = [f"**{player.name}**{standing}"]
    lines.append(
        f"Swiss record (W-D-L): {player.games_won}-{player.games_drawn}-{player.games_lost}, "
        f"byes: {player.byes}"
    )
    if player.wins_bracket or player.losses_bracket:
        lines.append(f"Top cut record (W-L): {player.wins_bracket}-{player.losses_bracket}")
    if player.win_rate is not None:
        lines.append(f"Win rate: {player.win_rate:.0%}")
    deck_name = player.leader or player.archetype
    if deck_name:
        lines.append(f"Deck: {deck_name}")

    if player.deck:
        for section, cards in player.deck.items():
            count = sum(c.count for c in cards.values())
            lines.append(f"\n### {section} ({count})")
            lines.extend(f"{c.count}x {name}" for name, c in cards.items())
    elif player.decklist:
        lines.append(f"\nDecklist:\n{player.decklist}")
    else:
        lines.append("\nNo decklist is public for this player.")

    exclude = {"decklist"} if player.deck else set()
    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_TOPDECK,
        structured_content={"tid": tid, **player.model_dump(mode="json", exclude=exclude)},
    )


def _aggregate_metagame(
    tournaments: list[TopDeckTournament],
) -> tuple[int, int, list[dict[str, object]]]:
    """Count entries, top cuts and match results per commander or archetype.

    Returns the entry count, the count of entries with a known deck, and one
    row per deck, most played first.
    Standings are in final rank order, so the first ``top_cut`` rows made the cut.
    Conversion counts only entries in tournaments that had a top cut.
    """
    entries = 0
    decks: dict[str, dict[str, int]] = {}
    for t in tournaments:
        for rank, s in enumerate(t.standings):
            entries += 1
            if not s.deck:
                continue
            row = decks.setdefault(
                s.deck,
                {"entries": 0, "cut_entries": 0, "top_cuts": 0, "wins": 0, "draws": 0, "losses": 0},
            )
            row["entries"] += 1
            if t.top_cut:
                row["cut_entries"] += 1
                row["top_cuts"] += rank < t.top_cut
            row["wins"] += s.wins
            row["draws"] += s.draws
            row["losses"] += s.losses

    known = sum(r["entries"] for r in decks.values())
    ranked = sorted(decks.items(), key=lambda item: (-item[1]["entries"], item[0]))
    return (
        entries,
        known,
        [
            {
                "deck": name,
                "entries": r["entries"],
                "share": _pct(r["entries"], known),
                "top_cuts": r["top_cuts"],
                "conversion": _pct(r["top_cuts"], r["cut_entries"]),
                "win_rate": _pct(r["wins"], r["wins"] + r["draws"] + r["losses"]),
            }
            for name, r in ranked
        ],
    )


@topdeck_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_CONSTRUCTED)
async def metagame(
    format: FormatParam,
    days: DaysParam = 30,
    min_players: MinPlayersParam = 16,
    limit: Annotated[
        int, Field(ge=1, le=100, description="Maximum commanders or archetypes to list")
    ] = 25,
) -> ToolResult:
    """Tournament metagame from TopDeck.gg results: the most played commanders or archetypes.

    For each deck: entries, share of entries with a known deck, top-cut
    entries, conversion rate (top cuts per entry, in tournaments with a cut)
    and match win rate. Commander formats group by commander; other formats
    by archetype.
    """
    client = _get_client()
    try:
        tournaments = await client.search_tournaments(format, days=days, min_players=min_players)
    except TopDeckError as exc:
        raise _tool_error(exc) from exc

    entries, known, decks = _aggregate_metagame(tournaments)

    fmt = tournaments[0].format if tournaments else format
    lines = [f"**{fmt} metagame** (last {days} days, tournaments with {min_players}+ players)"]
    if not decks:
        lines.append("No tournaments with known decks found.")
    else:
        lines.append(
            f"{len(tournaments)} tournaments, {entries} entries. "
            f"Deck known for {known} ({_pct(known, entries)}%)."
        )
        lines.append(
            "Win rate = wins / (wins + draws + losses). "
            "The baseline is 25% in 4-player pods (EDH) and 50% in 1v1 formats."
        )
        lines.append("")
        lines.append("| Deck | Entries | Share | Top cuts | Conversion | Win rate |")
        lines.append("|---|---|---|---|---|---|")
        for d in decks[:limit]:
            lines.append(
                f"| {d['deck']} | {d['entries']} | {_show_pct(d['share'])} | {d['top_cuts']} "
                f"| {_show_pct(d['conversion'])} | {_show_pct(d['win_rate'])} |"
            )

    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_TOPDECK,
        structured_content={
            "format": fmt,
            "days": days,
            "min_players": min_players,
            "tournaments": len(tournaments),
            "entries": entries,
            "known_entries": known,
            "decks": decks[:limit],
        },
    )
