"""Fixtures for live smoke tests — starts a real server subprocess over stdio."""

from __future__ import annotations

import os

import pytest_asyncio
from fastmcp import Client
from fastmcp.client.transports import StdioTransport


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def live_client():
    """FastMCP Client connected to one real server subprocess over stdio.

    Session-scoped so the server (and its bulk data download) starts once.
    Tests must run on the session event loop (see ``pytestmark`` in the tests).
    """
    transport = StdioTransport(
        command="uv",
        args=["run", "mtg-mcp-server"],
        env={**os.environ, "MTG_MCP_DISABLE_CACHE": "true"},
    )
    async with Client(transport, init_timeout=120) as client:
        yield client
