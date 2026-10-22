"""Shared test fixtures for MTG MCP server tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastmcp import Client

from mtg_mcp_server.server import mcp
from mtg_mcp_server.services.base import BaseClient
from mtg_mcp_server.services.edhrec import EDHRECClient
from mtg_mcp_server.services.moxfield import MoxfieldClient
from mtg_mcp_server.services.mtggoldfish import MTGGoldfishClient
from mtg_mcp_server.services.rules import RulesService
from mtg_mcp_server.services.scryfall import ScryfallClient
from mtg_mcp_server.services.seventeen_lands import SeventeenLandsClient
from mtg_mcp_server.services.spellbook import SpellbookClient


@pytest.fixture(autouse=True)
def _no_http_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip retry backoff and rate-limit pauses.

    HTTP is mocked, so the real waits only slow the suite: a 5xx test would
    otherwise sleep through every retry at the service's request rate.
    """

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(BaseClient._request.retry, "sleep", _no_sleep)
    for client_cls in BaseClient.__subclasses__():
        monkeypatch.setattr(client_cls, "rate_limit_rps", 1_000_000.0)


@pytest.fixture(autouse=True)
def _clear_caches():
    """Clear all service-level TTL caches before every test.

    Without this, cached results from one test leak into the next,
    causing spurious passes/failures (e.g., an error-path test gets
    a cached success from the happy-path test that ran first).
    """
    ScryfallClient._card_name_cache.clear()
    ScryfallClient._search_cache.clear()
    ScryfallClient._rulings_cache.clear()
    ScryfallClient._sets_cache.clear()
    SpellbookClient._combos_cache.clear()
    SpellbookClient._combo_cache.clear()
    SpellbookClient._decklist_combos_cache.clear()
    SpellbookClient._bracket_cache.clear()
    SeventeenLandsClient._card_ratings_cache.clear()
    SeventeenLandsClient._color_ratings_cache.clear()
    EDHRECClient._commander_cache.clear()
    EDHRECClient._synergy_cache.clear()
    MoxfieldClient._deck_cache.clear()
    MoxfieldClient._search_cache.clear()
    MoxfieldClient._user_search_cache.clear()
    MTGGoldfishClient._metagame_cache.clear()
    MTGGoldfishClient._archetype_cache.clear()
    MTGGoldfishClient._staples_cache.clear()


_RULES_TEXT = (Path(__file__).parent / "fixtures" / "rules" / "comprehensive_rules.txt").read_text(
    encoding="utf-8-sig"
)


@pytest.fixture
def offline_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve the Comprehensive Rules from the fixture file instead of wizards.com.

    The workflow server loads the rules at startup, so every test that starts it
    would otherwise download them.
    """

    async def _download(self: RulesService) -> str:
        return _RULES_TEXT

    monkeypatch.setattr(RulesService, "_download", _download)


@pytest.fixture
async def mcp_client(offline_rules: None):
    """In-memory MCP client connected to the orchestrator."""
    async with Client(transport=mcp) as client:
        yield client
