"""Tests for the TopDeck.gg MCP provider."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp import Client

from mtg_mcp_server.providers.topdeck import topdeck_mcp

FIXTURES = Path(__file__).parent.parent / "fixtures" / "topdeck"
BASE_URL = "https://topdeck.gg/api"
TID = "mbg-commanderpalooza-3-timetwister-event"
KRAUM_TYMNA = "Kraum, Ludevic's Opus / Tymna the Weaver"


def _load_fixture(name: str) -> object:
    """Load a TopDeck JSON fixture by filename."""
    return json.loads((FIXTURES / name).read_text())


def _mock_search(fixture: str) -> respx.Route:
    return respx.post(f"{BASE_URL}/v2/tournaments").mock(
        return_value=httpx.Response(200, json=_load_fixture(fixture))
    )


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch):
    """In-memory MCP client for the TopDeck provider, with a test API key."""
    monkeypatch.setenv("MTG_MCP_TOPDECK_API_KEY", "test-key")
    async with Client(transport=topdeck_mcp) as c:
        yield c


class TestSearchTournaments:
    @respx.mock
    async def test_lists_newest_first_with_winner(self, client: Client):
        _mock_search("bulk_edh.json")

        result = await client.call_tool("search_tournaments", {"format": "edh"})
        text = result.content[0].text

        assert "**2 EDH tournament(s)** in the last 30 days (16+ players)" in text
        assert text.index("animal-house-cards") < text.index(TID)
        assert f"`{TID}`): 2026-10-24, 20 players, top 16, Wyandotte, MI" in text
        assert f"Winner: Player 4 ({KRAUM_TYMNA})" in text
        assert "Test Event" not in text
        assert "Data provided by [TopDeck.gg](https://topdeck.gg)" in text

        sc = result.structured_content
        assert sc is not None
        assert sc["total"] == 2
        assert sc["tournaments"][1]["winner_deck"] == KRAUM_TYMNA

    @respx.mock
    async def test_limit_truncates(self, client: Client):
        _mock_search("bulk_edh.json")

        result = await client.call_tool("search_tournaments", {"format": "EDH", "limit": 1})

        assert "Showing the newest 1." in result.content[0].text
        assert result.structured_content is not None
        assert len(result.structured_content["tournaments"]) == 1

    @respx.mock
    async def test_no_results(self, client: Client):
        _mock_search("bulk_edh.json").mock(return_value=httpx.Response(200, json=[]))

        result = await client.call_tool("search_tournaments", {"format": "Vintage"})

        assert "No Vintage tournaments with 16+ players" in result.content[0].text

    @respx.mock
    async def test_unknown_format_is_tool_error(self, client: Client):
        result = await client.call_tool(
            "search_tournaments", {"format": "commander"}, raise_on_error=False
        )

        assert result.is_error
        assert "Valid formats: EDH" in result.content[0].text

    @respx.mock
    async def test_bad_key_names_the_setting(self, client: Client):
        respx.post(f"{BASE_URL}/v2/tournaments").mock(
            return_value=httpx.Response(401, json={"error": "Invalid API key"})
        )

        result = await client.call_tool(
            "search_tournaments", {"format": "EDH"}, raise_on_error=False
        )

        assert result.is_error
        assert "MTG_MCP_TOPDECK_API_KEY" in result.content[0].text


class TestTournament:
    @respx.mock
    async def test_shows_details_and_top_rows(self, client: Client):
        _mock_search("tournament.json")

        result = await client.call_tool("tournament", {"tid": TID, "top": 3})
        text = result.content[0].text

        assert "(EDH)" in text
        assert "Top cut: 16" in text
        assert "### Top 3 (record W-D-L)" in text
        assert f"1. Player 4 (`p4`), 5-1-2: {KRAUM_TYMNA}" in text
        assert "4. " not in text

        sc = result.structured_content
        assert sc is not None
        assert sc["players"] == 20
        assert [row["rank"] for row in sc["standings"]] == [1, 2, 3]

    @respx.mock
    async def test_unknown_tournament(self, client: Client):
        respx.post(f"{BASE_URL}/v2/tournaments").mock(return_value=httpx.Response(200, json=[]))

        result = await client.call_tool("tournament", {"tid": "nope"}, raise_on_error=False)

        assert result.is_error
        assert "not found or not finished" in result.content[0].text


class TestPlayerDeck:
    @respx.mock
    async def test_renders_record_and_deck_sections(self, client: Client):
        respx.get(f"{BASE_URL}/v2/tournaments/{TID}/players/p4").mock(
            return_value=httpx.Response(200, json=_load_fixture("player.json"))
        )

        result = await client.call_tool("player_deck", {"tid": TID, "player_id": "p4"})
        text = result.content[0].text

        assert "**Player 4**, standing 1" in text
        assert "Swiss record (W-D-L): 3-1-2, byes: 0" in text
        assert "Top cut record (W-L): 2-0" in text
        assert f"Deck: {KRAUM_TYMNA}" in text
        assert "### Commanders (2)" in text
        assert "### Mainboard (98)" in text
        assert "1x Ad Nauseam" in text
        assert "metadata" not in text

        sc = result.structured_content
        assert sc is not None
        assert "decklist" not in sc
        assert sc["deck"]["Commanders"]["Tymna the Weaver"]["count"] == 1

    @respx.mock
    async def test_falls_back_to_decklist_text(self, client: Client):
        player = _load_fixture("player.json")
        assert isinstance(player, dict)
        player["deckObj"] = None
        respx.get(f"{BASE_URL}/v2/tournaments/{TID}/players/p4").mock(
            return_value=httpx.Response(200, json=player)
        )

        result = await client.call_tool("player_deck", {"tid": TID, "player_id": "p4"})

        assert "Decklist:\n~~Commanders~~\n1 Kraum, Ludevic's Opus" in result.content[0].text

    @respx.mock
    async def test_unknown_player(self, client: Client):
        respx.get(f"{BASE_URL}/v2/tournaments/{TID}/players/nobody").mock(
            return_value=httpx.Response(404, json=_load_fixture("player_not_found.json"))
        )

        result = await client.call_tool(
            "player_deck", {"tid": TID, "player_id": "nobody"}, raise_on_error=False
        )

        assert result.is_error
        assert "not found in TopDeck.gg tournament" in result.content[0].text


class TestMetagame:
    @respx.mock
    async def test_counts_hand_checked(self, client: Client):
        _mock_search("bulk_edh.json")

        result = await client.call_tool("metagame", {"format": "EDH"})
        sc = result.structured_content
        assert sc is not None

        # 2 events after the future-dated one is dropped: 20 + 20 rows.
        assert sc["tournaments"] == 2
        assert sc["entries"] == 40
        assert sc["known_entries"] == 22
        assert sc["field_win_rate"] == 33.0
        # Kraum/Tymna: 6 rows in the 16-cut event, at ranks 1, 10, 12, 13, 15 and 18.
        # Records 5-1-2, 2-4-1, 2-3-2, 2-3-2, 2-3-2, 1-2-2.
        top = sc["decks"][0]
        assert top["deck"] == KRAUM_TYMNA
        assert top["entries"] == 6
        assert top["share"] == 27.3  # 6 / 22
        assert top["top_cuts"] == 5
        assert top["conversion"] == 83.3  # 5 / 6
        assert top["win_rate"] == 34.1  # 14 / (14 + 16 + 11)

        text = result.content[0].text
        assert "**EDH metagame** (last 30 days, tournaments with 16+ players)" in text
        assert "40 entries. Deck known for 22 (55.0%)." in text
        assert f"| {KRAUM_TYMNA} | 6 | 27.3% | 5 | 83.3% | 34.1% |" in text
        assert "Field average: 33.0%." in text  # 66 / (66 + 54 + 80) over all 40 rows

    @respx.mock
    async def test_archetype_formats(self, client: Client):
        _mock_search("bulk_modern.json")

        result = await client.call_tool("metagame", {"format": "modern", "limit": 3})
        sc = result.structured_content
        assert sc is not None

        # Only the second event has archetype labels; Broodscale sits at ranks 4 and 7 of a top 8.
        assert sc["known_entries"] == 10
        assert len(sc["decks"]) == 3
        broodscale = sc["decks"][0]
        assert broodscale["deck"] == "Broodscale"
        assert broodscale["entries"] == 2
        assert broodscale["top_cuts"] == 2
        assert broodscale["win_rate"] == 53.8  # 7 / (7 + 3 + 3)

    @respx.mock
    async def test_no_tournaments(self, client: Client):
        respx.post(f"{BASE_URL}/v2/tournaments").mock(return_value=httpx.Response(200, json=[]))

        result = await client.call_tool("metagame", {"format": "Legacy"})

        assert "No tournaments with known decks found." in result.content[0].text


async def test_tools_fail_cleanly_without_key(monkeypatch: pytest.MonkeyPatch):
    """Run alone with no key, the provider starts and its tools return an error."""
    monkeypatch.delenv("MTG_MCP_TOPDECK_API_KEY", raising=False)
    monkeypatch.chdir(FIXTURES)  # no .env here
    async with Client(transport=topdeck_mcp) as c:
        result = await c.call_tool("metagame", {"format": "EDH"}, raise_on_error=False)
    assert result.is_error
