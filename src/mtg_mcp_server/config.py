"""Application configuration via environment variables.

All settings use the ``MTG_MCP_`` prefix and can be overridden via a ``.env``
file. No credentials are required, except an optional free TopDeck.gg API key.

Example::

    MTG_MCP_ENABLE_EDHREC = false  # Disable fragile EDHREC scraping
"""

from __future__ import annotations

from pydantic import SecretStr  # noqa: TC002 (pydantic)
from pydantic_settings import BaseSettings

__all__ = ["Settings"]


class Settings(BaseSettings):
    """MTG MCP server settings loaded from environment variables.

    All fields have sensible defaults and can be overridden with
    ``MTG_MCP_``-prefixed environment variables or a ``.env`` file.
    """

    # --- Logging ---
    log_level: str = "INFO"

    # --- Backend URLs ---
    # Each service client reads its base URL from here so tests can point
    # at a local mock server via env var override.
    scryfall_base_url: str = "https://api.scryfall.com"
    spellbook_base_url: str = "https://backend.commanderspellbook.com"
    seventeen_lands_base_url: str = "https://www.17lands.com"
    edhrec_base_url: str = "https://json.edhrec.com"
    moxfield_base_url: str = "https://api2.moxfield.com"
    mtggoldfish_base_url: str = "https://www.mtggoldfish.com"
    topdeck_base_url: str = "https://topdeck.gg/api"

    # --- Feature flags ---
    # Optional backends can be disabled without code changes.
    enable_17lands: bool = True
    enable_edhrec: bool = True  # Behind flag — scrapes undocumented endpoints
    enable_moxfield: bool = True  # Behind flag — reverse-engineered API
    enable_mtggoldfish: bool = True  # Behind flag — scrapes HTML (no API)
    enable_bulk_data: bool = True  # Scryfall Oracle Cards bulk download (~30MB)

    # --- TopDeck.gg ---
    # Free key from https://topdeck.gg/developers. The topdeck_ tools mount only when it is set.
    topdeck_api_key: SecretStr | None = None

    # --- Caching ---
    disable_cache: bool = False  # Set True in tests to bypass TTLCache

    # --- Scryfall Bulk Data ---
    bulk_data_refresh_hours: int = 12

    # --- Comprehensive Rules ---
    rules_url: str = "https://media.wizards.com/2026/downloads/MagicCompRules%2020260925.txt"
    rules_refresh_hours: int = 168  # Weekly check (rules update ~4x/year)
    enable_rules: bool = True

    model_config = {"env_prefix": "MTG_MCP_", "env_file": ".env", "extra": "ignore"}
