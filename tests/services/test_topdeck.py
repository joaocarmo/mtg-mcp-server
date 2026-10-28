"""Tests for the TopDeck.gg service client."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest
import respx

from mtg_mcp_server.services.topdeck import (
    TopDeckClient,
    TopDeckError,
    TournamentNotFoundError,
    resolve_format,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "topdeck"
BASE_URL = "https://topdeck.gg/api"
TID = "mbg-commanderpalooza-3-timetwister-event"


def _load_fixture(name: str) -> object:
    """Load a TopDeck JSON fixture by filename."""
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
async def client():
    """A TopDeckClient with a test API key."""
    async with TopDeckClient(base_url=BASE_URL, api_key="test-key") as c:
        yield c


class TestResolveFormat:
    """Format names must reach the API in its exact, case-sensitive spelling."""

    def test_matches_case_insensitively(self):
        assert resolve_format("edh") == "EDH"
        assert resolve_format(" pauper edh ") == "Pauper EDH"
        assert resolve_format("MODERN") == "Modern"

    def test_unknown_format_lists_valid_names(self):
        with pytest.raises(TopDeckError, match="Valid formats: EDH, Pauper EDH"):
            resolve_format("commander")


class TestSearchTournaments:
    """POST /v2/tournaments in query mode."""

    @respx.mock
    async def test_sends_key_and_query(self, client: TopDeckClient):
        route = respx.post(f"{BASE_URL}/v2/tournaments").mock(
            return_value=httpx.Response(200, json=_load_fixture("bulk_edh.json"))
        )

        await client.search_tournaments("edh", days=7, min_players=16)

        request = route.calls.last.request
        assert request.headers["Authorization"] == "test-key"
        assert json.loads(request.content) == {
            "game": "Magic: The Gathering",
            "format": "EDH",
            "last": 7,
            "participantMin": 16,
            "columns": ["name", "id", "wins", "draws", "losses"],
        }

    @respx.mock
    async def test_omits_participant_min_when_unset(self, client: TopDeckClient):
        route = respx.post(f"{BASE_URL}/v2/tournaments").mock(
            return_value=httpx.Response(200, json=[])
        )

        await client.search_tournaments("Modern")

        assert "participantMin" not in json.loads(route.calls.last.request.content)

    @respx.mock
    async def test_parses_and_drops_future_events(self, client: TopDeckClient):
        events = _load_fixture("bulk_edh.json")
        assert isinstance(events, list)
        # The fixture's third event is a test event dated ahead; keep it in the future.
        events[2]["startDate"] = int(time.time()) + 10**7
        respx.post(f"{BASE_URL}/v2/tournaments").mock(return_value=httpx.Response(200, json=events))

        result = await client.search_tournaments("EDH")

        assert [t.tid for t in result] == [
            "animal-house-cards-cedh-piloting-practice-372",
            TID,
        ]
        big = result[1]
        assert big.top_cut == 16
        assert big.location.city == "Wyandotte"
        winner = big.standings[0]
        assert (winner.wins, winner.draws, winner.losses) == (5, 1, 2)
        assert winner.deck == "Kraum, Ludevic's Opus / Tymna the Weaver"

    @respx.mock
    async def test_archetype_formats_expose_archetype(self, client: TopDeckClient):
        respx.post(f"{BASE_URL}/v2/tournaments").mock(
            return_value=httpx.Response(200, json=_load_fixture("bulk_modern.json"))
        )

        result = await client.search_tournaments("Modern")

        decks = {s.deck for t in result for s in t.standings}
        assert "Eldrazi Tron" in decks
        assert all(s.leader is None for t in result for s in t.standings)

    @respx.mock
    async def test_unknown_format_makes_no_request(self, client: TopDeckClient):
        route = respx.post(f"{BASE_URL}/v2/tournaments")

        with pytest.raises(TopDeckError, match="Unknown TopDeck format"):
            await client.search_tournaments("commander")
        assert not route.called

    @respx.mock
    async def test_bad_key_raises_with_status(self, client: TopDeckClient):
        respx.post(f"{BASE_URL}/v2/tournaments").mock(
            return_value=httpx.Response(401, json={"error": "Invalid API key"})
        )

        with pytest.raises(TopDeckError) as exc_info:
            await client.search_tournaments("EDH")
        assert exc_info.value.status_code == 401

    @respx.mock
    async def test_unexpected_shape_raises(self, client: TopDeckClient):
        respx.post(f"{BASE_URL}/v2/tournaments").mock(
            return_value=httpx.Response(200, json={"error": "nope"})
        )

        with pytest.raises(TopDeckError, match="unexpected search response"):
            await client.search_tournaments("EDH")

    @respx.mock
    async def test_results_are_cached(self, client: TopDeckClient):
        route = respx.post(f"{BASE_URL}/v2/tournaments").mock(
            return_value=httpx.Response(200, json=[])
        )

        await client.search_tournaments("edh", days=30, min_players=16)
        await client.search_tournaments("EDH", days=30, min_players=16)

        assert route.call_count == 1


class TestGetTournament:
    """POST /v2/tournaments in TID mode."""

    @respx.mock
    async def test_returns_tournament(self, client: TopDeckClient):
        route = respx.post(f"{BASE_URL}/v2/tournaments").mock(
            return_value=httpx.Response(200, json=_load_fixture("tournament.json"))
        )

        result = await client.get_tournament(TID)

        assert json.loads(route.calls.last.request.content)["TID"] == TID
        assert result.name.startswith("MBG Commanderpalooza")
        assert len(result.standings) == 20

    @respx.mock
    async def test_empty_result_is_not_found(self, client: TopDeckClient):
        respx.post(f"{BASE_URL}/v2/tournaments").mock(return_value=httpx.Response(200, json=[]))

        with pytest.raises(TournamentNotFoundError, match="not found or not finished"):
            await client.get_tournament("no-such-event")


class TestGetPlayer:
    """GET /v2/tournaments/{TID}/players/{ID}."""

    @respx.mock
    async def test_parses_record_and_deck(self, client: TopDeckClient):
        respx.get(f"{BASE_URL}/v2/tournaments/{TID}/players/p4").mock(
            return_value=httpx.Response(200, json=_load_fixture("player.json"))
        )

        player = await client.get_player(TID, "p4")

        assert player.standing == 1
        assert (player.games_won, player.wins_bracket) == (3, 2)
        assert list(player.deck) == ["Commanders", "Mainboard"]
        assert player.deck["Commanders"]["Tymna the Weaver"].count == 1
        assert sum(c.count for c in player.deck["Mainboard"].values()) == 98
        assert player.decklist is not None
        assert player.decklist.startswith("~~Commanders~~\n1 Kraum, Ludevic's Opus\n")

    @respx.mock
    async def test_404_is_not_found(self, client: TopDeckClient):
        respx.get(f"{BASE_URL}/v2/tournaments/{TID}/players/nobody").mock(
            return_value=httpx.Response(404, json=_load_fixture("player_not_found.json"))
        )

        with pytest.raises(TournamentNotFoundError):
            await client.get_player(TID, "nobody")

    @respx.mock
    async def test_server_error_is_topdeck_error(self, client: TopDeckClient):
        respx.get(f"{BASE_URL}/v2/tournaments/{TID}/players/p4").mock(
            return_value=httpx.Response(500, json={"error": "Internal server error"})
        )

        with pytest.raises(TopDeckError) as exc_info:
            await client.get_player(TID, "p4")
        assert not isinstance(exc_info.value, TournamentNotFoundError)
