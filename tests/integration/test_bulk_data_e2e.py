"""Integration tests for Scryfall bulk data through the full MCP pipeline.

Tests exercise bulk_card_lookup and bulk_card_search
via the orchestrator with fixture-mocked HTTP backends.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastmcp import Client


pytestmark = pytest.mark.integration


class TestBulkCardLookup:
    """Bulk card lookup through the orchestrator."""

    async def test_sol_ring_returns_artifact_not_minigame(self, mcp_client: Client):
        """bulk_card_lookup returns the real Sol Ring (Artifact), not the minigame version."""
        result = await mcp_client.call_tool("bulk_card_lookup", {"name": "Sol Ring"})
        text = result.content[0].text
        assert "Artifact" in text
        assert "acmm" not in text

    async def test_sol_ring_has_prices(self, mcp_client: Client):
        """bulk_card_lookup output includes price data."""
        result = await mcp_client.call_tool("bulk_card_lookup", {"name": "Sol Ring"})
        text = result.content[0].text
        assert "$1.50" in text

    async def test_sol_ring_has_legalities(self, mcp_client: Client):
        """bulk_card_lookup output includes legality information."""
        result = await mcp_client.call_tool("bulk_card_lookup", {"name": "Sol Ring"})
        text = result.content[0].text
        assert "commander" in text.lower()
        assert "legal" in text.lower()

    async def test_sol_ring_has_edhrec_rank(self, mcp_client: Client):
        """bulk_card_lookup output includes EDHREC rank."""
        result = await mcp_client.call_tool("bulk_card_lookup", {"name": "Sol Ring"})
        text = result.content[0].text
        assert "EDHREC Rank" in text

    async def test_dfc_lookup_by_front_face(self, mcp_client: Client):
        """bulk_card_lookup finds a DFC by front-face name and includes Creature type."""
        result = await mcp_client.call_tool("bulk_card_lookup", {"name": "Delver of Secrets"})
        text = result.content[0].text
        assert "Creature" in text

    async def test_not_found_returns_error(self, mcp_client: Client):
        """bulk_card_lookup returns an error for a nonexistent card."""
        result = await mcp_client.call_tool(
            "bulk_card_lookup", {"name": "Nonexistent Card"}, raise_on_error=False
        )
        assert result.is_error


class TestBulkCardSearch:
    """Bulk card search through the orchestrator."""

    async def test_search_by_name(self, mcp_client: Client):
        """bulk_card_search by name finds Sol Ring."""
        result = await mcp_client.call_tool("bulk_card_search", {"query": "Sol"})
        text = result.content[0].text
        assert "Sol Ring" in text

    async def test_search_excludes_nonplayable(self, mcp_client: Client):
        """bulk_card_search for 'Sol Ring' excludes the minigame version."""
        result = await mcp_client.call_tool("bulk_card_search", {"query": "Sol Ring"})
        text = result.content[0].text
        assert "acmm" not in text

    async def test_search_by_type_excludes_tokens(self, mcp_client: Client):
        """bulk_card_search by type for Creature does not return token entries."""
        result = await mcp_client.call_tool(
            "bulk_card_search", {"query": "Creature", "search_field": "type"}
        )
        text = result.content[0].text
        assert "Token" not in text

    async def test_search_by_text(self, mcp_client: Client):
        """bulk_card_search by oracle text for 'Add' finds Sol Ring."""
        result = await mcp_client.call_tool(
            "bulk_card_search", {"query": "Add", "search_field": "text"}
        )
        text = result.content[0].text
        assert "Sol Ring" in text
