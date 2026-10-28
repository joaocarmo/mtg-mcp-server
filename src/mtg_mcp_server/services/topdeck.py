"""TopDeck.gg API client for tournament results.

Uses the documented v2 API at ``topdeck.gg/api``. Every request needs a free
API key, so the orchestrator mounts the provider only when
``MTG_MCP_TOPDECK_API_KEY`` is set.
"""

from __future__ import annotations

import time
from typing import Self

import structlog
from cachetools import TTLCache
from pydantic import ValidationError

from mtg_mcp_server.services.base import BaseClient, ServiceError
from mtg_mcp_server.services.cache import async_cached
from mtg_mcp_server.types import TopDeckPlayer, TopDeckTournament

log = structlog.get_logger(service="topdeck")

GAME = "Magic: The Gathering"

# Magic formats exactly as the API expects them (case sensitive).
TOPDECK_MTG_FORMATS = (
    "EDH",
    "Pauper EDH",
    "Casual EDH",
    "Standard",
    "Pioneer",
    "Modern",
    "Legacy",
    "Pauper",
    "Vintage",
    "Premodern",
    "Sealed",
    "Limited",
    "Duel Commander",
    "Old School 93/94",
    "Canadian Highlander",
    "Tiny Leaders",
    "Team Trios",
    "Two-Headed Giant",
    "EDH Draft",
    "Timeless",
    "Historic",
    "Explorer",
    "7pt Highlander",
    "Oathbreaker",
    "Other",
)

# Standings columns for every search. Leaving out "decklist" keeps responses small;
# leader and archetype are always included.
_COLUMNS = ["name", "id", "wins", "draws", "losses"]


class TopDeckError(ServiceError):
    """TopDeck.gg API error."""


class TournamentNotFoundError(TopDeckError):
    """Tournament or player was not found, or the tournament has not finished."""


def resolve_format(raw: str) -> str:
    """Return the API spelling of a Magic format, matched case-insensitively.

    Raises:
        TopDeckError: If the format is not one TopDeck supports.
    """
    wanted = raw.strip().lower()
    for fmt in TOPDECK_MTG_FORMATS:
        if fmt.lower() == wanted:
            return fmt
    raise TopDeckError(
        f"Unknown TopDeck format: '{raw}'. Valid formats: {', '.join(TOPDECK_MTG_FORMATS)}"
    )


class TopDeckClient(BaseClient):
    """Async client for the TopDeck.gg v2 tournaments API."""

    # 1h caches: these methods serve completed tournaments, which no longer change.
    _search_cache: TTLCache = TTLCache(maxsize=50, ttl=3600)
    _tournament_cache: TTLCache = TTLCache(maxsize=100, ttl=3600)
    _player_cache: TTLCache = TTLCache(maxsize=200, ttl=3600)

    # The API allows 100 requests per minute on most endpoints.
    rate_limit_rps = 1.5

    def __init__(self, base_url: str, api_key: str) -> None:
        super().__init__(base_url=base_url)
        self._api_key = api_key

    async def __aenter__(self) -> Self:
        """Create the httpx client and attach the API key header."""
        await super().__aenter__()
        assert self._client is not None
        self._client.headers["Authorization"] = self._api_key
        return self

    async def search_tournaments(
        self, fmt: str, days: int = 30, min_players: int | None = None
    ) -> list[TopDeckTournament]:
        """Search completed Magic tournaments in a format.

        Args:
            fmt: Format name, matched case-insensitively against ``TOPDECK_MTG_FORMATS``.
            days: How many days back to search.
            min_players: Minimum participant count.

        Returns:
            Tournaments that have already started, newest first.

        Raises:
            TopDeckError: On an unknown format or API errors.
        """
        # Resolve before the cached call so "edh" and "EDH" share one cache entry.
        return await self._search(resolve_format(fmt), days, min_players)

    @async_cached(_search_cache)
    async def _search(
        self, fmt: str, days: int, min_players: int | None
    ) -> list[TopDeckTournament]:
        body: dict[str, object] = {"game": GAME, "format": fmt, "last": days, "columns": _COLUMNS}
        if min_players is not None:
            body["participantMin"] = min_players
        log.debug("search_tournaments", format=fmt, days=days, min_players=min_players)
        tournaments = await self._post_tournaments(body)
        # The API also returns organizers' test events dated years ahead.
        now = time.time()
        started = [t for t in tournaments if t.start_date <= now]
        return sorted(started, key=lambda t: t.start_date, reverse=True)

    @async_cached(_tournament_cache)
    async def get_tournament(self, tid: str) -> TopDeckTournament:
        """Fetch one completed tournament with its standings.

        Raises:
            TournamentNotFoundError: If the ID is unknown or the tournament has not finished.
            TopDeckError: On other API errors.
        """
        log.debug("get_tournament", tid=tid)
        tournaments = await self._post_tournaments({"TID": tid, "columns": _COLUMNS})
        if not tournaments:
            raise TournamentNotFoundError(f"Tournament not found or not finished: '{tid}'")
        return tournaments[0]

    @async_cached(_player_cache)
    async def get_player(self, tid: str, player_id: str) -> TopDeckPlayer:
        """Fetch a player's record and deck in one tournament.

        Raises:
            TournamentNotFoundError: If the tournament or player does not exist (404).
            TopDeckError: On other API errors.
        """
        log.debug("get_player", tid=tid, player_id=player_id)
        try:
            response = await self._get(f"/v2/tournaments/{tid}/players/{player_id}")
        except ServiceError as exc:
            if exc.status_code == 404:
                raise TournamentNotFoundError(
                    f"Player '{player_id}' not found in tournament '{tid}'", status_code=404
                ) from exc
            raise TopDeckError(exc.message, status_code=exc.status_code) from exc
        try:
            return TopDeckPlayer.model_validate(response.json())
        except (ValidationError, ValueError) as exc:
            raise TopDeckError(f"TopDeck returned an unexpected player response: {exc}") from exc

    async def _post_tournaments(self, body: dict[str, object]) -> list[TopDeckTournament]:
        """POST to the tournament search endpoint and parse the result list."""
        try:
            response = await self._post("/v2/tournaments", json=body)
        except ServiceError as exc:
            raise TopDeckError(exc.message, status_code=exc.status_code) from exc
        try:
            data = response.json()
            if not isinstance(data, list):
                raise ValueError(f"expected a list, got {type(data).__name__}")
            return [TopDeckTournament.model_validate(item) for item in data]
        except (ValidationError, ValueError) as exc:
            raise TopDeckError(f"TopDeck returned an unexpected search response: {exc}") from exc
