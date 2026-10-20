<!-- mcp-name: io.github.j4th/mtg-mcp-server -->
# mtg-mcp-server

[![CI](https://github.com/j4th/mtg-mcp-server/actions/workflows/ci.yml/badge.svg)](https://github.com/j4th/mtg-mcp-server/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/mtg-mcp-server)](https://pypi.org/project/mtg-mcp-server/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue?logo=python&logoColor=white)](https://github.com/j4th/mtg-mcp-server)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![codecov](https://codecov.io/gh/j4th/mtg-mcp-server/graph/badge.svg)](https://codecov.io/gh/j4th/mtg-mcp-server)
[![CodeQL](https://github.com/j4th/mtg-mcp-server/workflows/CodeQL/badge.svg)](https://github.com/j4th/mtg-mcp-server/actions/workflows/codeql.yml)
[![Smithery](https://smithery.ai/badge/@j4th/mtg-mcp-server)](https://smithery.ai/server/@j4th/mtg-mcp-server)
[![Dependabot](https://img.shields.io/badge/dependabot-enabled-blue?logo=dependabot)](https://github.com/j4th/mtg-mcp-server/security/dependabot)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

69 tools, 19 prompts, and 21 resources that give AI assistants deep access to Magic: The Gathering -- card data, combos, draft analytics, Commander metagame, competitive constructed, sideboard strategy, deck building, rules engine, and more. Works with Claude Code, Claude Desktop, or any MCP client.

> Built on data from [Scryfall](https://scryfall.com), [Commander Spellbook](https://commanderspellbook.com), [17Lands](https://www.17lands.com), [EDHREC](https://edhrec.com), [Moxfield](https://www.moxfield.com), [Spicerack](https://spicerack.gg), and [MTGGoldfish](https://www.mtggoldfish.com). See [Data Sources & Attribution](#data-sources--attribution) for details and usage terms.

## What You Can Do

Ask your AI assistant questions like these and it will use the MTG tools automatically:

**Commander**
- "Show me everything about Muldrotha as a commander"
- "What are the best budget upgrades for my Atraxa deck under $5?"
- "Compare Muldrotha vs Meren vs Karador as graveyard commanders"

**Draft & Limited**
- "What are the best commons in Foundations for draft?"
- "Rank these cards for my draft pack: Bitter Triumph, Monstrous Rage, Torch the Tower"
- "Build a sealed deck from this pool: [list]"

**Deck Building**
- "Validate my Modern decklist"
- "Suggest a mana base for my 3-color Commander deck"
- "Find cards that synergize with sacrifice themes in Golgari"

**Rules**
- "How do deathtouch and trample interact?"
- "Resolve this combat scenario: my 3/3 with first strike blocks their 5/5 with trample"

**Constructed**
- "What does the Modern metagame look like right now?"
- "Show me the stock Boros Energy decklist for Modern"
- "Build me a sideboard for this Pioneer deck"
- "Give me a sideboard guide for my deck against Azorius Control"

### See It in Action

> "Compare Muldrotha, Meren, and Karador as graveyard commanders"

```
                     Muldrotha            Meren               Karador
Mana Cost            {3}{B}{G}{U}         {2}{B}{G}           {5}{W}{B}{G}
Color Identity       BGU (Sultai)         BG (Golgari)        BGW (Abzan)
Stats                6/6                  3/4                  3/4
EDHREC Rank          #1,137               #1,476              #9,894
Total Decks          22,460               19,919              6,305
Combo Count          10                   1                   10

Top Staples:
  Muldrotha           Spore Frog (+53%), Sakura-Tribe Elder (+36%), Eternal Witness (+27%)
  Meren               Spore Frog (+70%), Sakura-Tribe Elder (+55%), Viscera Seer (+52%)
  Karador             Karmic Guide (+51%), Satyr Wayfinder (+49%), Sun Titan (+48%)
```

> "What are the best commons in Foundations for draft?"

```
Foundations (FDN) — PremierDraft · Median GIH WR: 54.7%

Rank  Card               Color  GIH WR   ALSA   IWD      Games
1     Bake into a Pie    B      58.4%    3.1    +5.3%    354,741
2     Burst Lightning    R      58.2%    3.3    +3.0%    338,888
3     Refute             U      58.1%    5.3    +4.3%    321,280
4     Stab               B      57.9%    3.4    +4.5%    376,569
5     Dazzling Angel     W      57.8%    3.2    +2.4%    317,648

Trap rares: Doubling Season (39.4%), Thousand-Year Storm (35.2%) ...
```

More examples with real tool output in the [Cookbook](docs/COOKBOOK.md).

## Install

No API keys needed -- all data sources are public.

### Hosted (zero setup)

The fastest way to get started. No Python install required. Works on mobile.

**Via the UI** (Claude Desktop or claude.ai): Settings → Connectors → Add custom connector → paste the URL:

```
https://mtg-mcp-server.fastmcp.app/mcp
```

**Via config file** (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "mtg": {
      "type": "url",
      "url": "https://mtg-mcp-server.fastmcp.app/mcp"
    }
  }
}
```

### Claude Code

```bash
claude mcp add mtg -- uvx mtg-mcp-server
```

Or via the UI: Settings → MCP Servers → Add server → enter `uvx mtg-mcp-server` as the command.

### Claude Desktop (local)

Runs on your machine. Requires Python 3.12+.

```json
{
  "mcpServers": {
    "mtg": {
      "command": "uvx",
      "args": ["mtg-mcp-server"]
    }
  }
}
```

### PyPI

```bash
# Run directly (no install)
uvx mtg-mcp-server

# Install globally
uv tool install mtg-mcp-server

# Add to a project
uv add mtg-mcp-server
```

### Development

```bash
git clone https://github.com/j4th/mtg-mcp-server.git
cd mtg-mcp-server
mise install          # Installs Python 3.12, uv, ruff, ty
mise run setup        # Creates venv, installs dependencies

uv run mtg-mcp-server # Run the server
```

Claude Code config for local development:

```json
{
  "mcpServers": {
    "mtg": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mtg-mcp-server", "mtg-mcp-server"]
    }
  }
}
```

## Configuration

All settings are `MTG_MCP_` environment variables with working defaults (full list: `src/mtg_mcp_server/config.py`). Each optional backend can be turned off with `MTG_MCP_ENABLE_<NAME>=false`, where `<NAME>` is `17LANDS`, `EDHREC`, `MOXFIELD`, `SPICERACK`, `MTGGOLDFISH`, `BULK_DATA` (skips a ~30MB download) or `RULES`.

```bash
uvx --env MTG_MCP_ENABLE_EDHREC=false mtg-mcp-server
```

## Tools

Full inputs/outputs: [docs/TOOL_DESIGN.md](docs/TOOL_DESIGN.md).

| Domain | Tools |
|--------|-------|
| Card data (`scryfall_`) | `search_cards`, `card_details`, `card_price`, `card_rulings`, `set_info`, `whats_new` |
| Bulk data (`bulk_`, rate-limit-free) | `card_lookup`, `card_search`, `format_legality`, `format_search`, `format_staples`, `ban_list`, `card_in_formats`, `random_card`, `similar_cards` |
| Combos (`spellbook_`) | `find_combos`, `combo_details`, `find_decklist_combos`, `estimate_bracket` |
| Draft analytics (`draft_`) | `card_ratings`, `archetype_stats` |
| Commander metagame (`edhrec_`) | `commander_staples`, `card_synergy` |
| Decklists (`moxfield_`) | `decklist`, `deck_info`, `search_decks`, `user_decks` |
| Tournaments (`spicerack_`) | `recent_tournaments`, `tournament_results`, `format_decklists` |
| Metagame (`goldfish_`) | `metagame`, `archetype_list`, `format_staples`, `deck_price` |
| Commander workflows | `commander_overview`, `evaluate_upgrade`, `card_comparison`, `budget_upgrade`, `commander_comparison`, `color_identity_staples`, `tribal_staples`, `precon_upgrade`, `suggest_cuts`, `deck_analysis` |
| Deck building | `theme_search`, `build_around`, `complete_deck`, `deck_validate`, `suggest_mana_base`, `price_comparison` |
| Draft workflows | `draft_pack_pick`, `set_overview`, `sealed_pool_build`, `draft_signal_read`, `draft_log_review` |
| Constructed | `rotation_check`, `metagame_snapshot`, `archetype_decklist`, `archetype_comparison`, `format_entry_guide`, `suggest_sideboard`, `sideboard_guide`, `sideboard_matrix` |
| Rules engine | `rules_lookup`, `keyword_explain`, `rules_interaction`, `rules_scenario`, `combat_calculator` |

## Architecture

Built on FastMCP 3.x: each data source is an independent sub-server mounted under its namespace on one orchestrator; workflow tools compose across sources and tolerate partial failure. Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Development commands and workflow: [CONTRIBUTING.md](CONTRIBUTING.md).

## Documentation

| Doc | What it covers |
|-----|----------------|
| [COOKBOOK.md](docs/COOKBOOK.md) | Usage recipes with real output |
| [TOOL_DESIGN.md](docs/TOOL_DESIGN.md) | All tools, prompts, and resources with inputs/outputs |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Architecture, FastMCP patterns, design decisions |
| [SERVICE_CONTRACTS.md](docs/SERVICE_CONTRACTS.md) | Per-backend endpoints, auth, rate limits, quirks, feature flags |
| [DATA_SOURCES.md](docs/DATA_SOURCES.md) | Data sources evaluated, stability, status |
| [CACHING_DESIGN.md](docs/CACHING_DESIGN.md) | TTL cache strategy and bulk data layer |
| [CHANGELOG.md](CHANGELOG.md) | Version history |

## Data Sources & Attribution

This project composes data from multiple third-party services:

- **[Scryfall](https://scryfall.com)** -- Card database, prices, rulings, search, bulk data ([API guidelines](https://scryfall.com/docs/api))
- **[Commander Spellbook](https://commanderspellbook.com)** -- Combo search, bracket estimation ([MIT license](https://github.com/SpaceCowMedia/commander-spellbook-backend))
- **[17Lands](https://www.17lands.com)** -- Draft card ratings, archetype win rates ([usage guidelines](https://www.17lands.com/usage_guidelines))
- **[EDHREC](https://edhrec.com)** -- Commander staples, synergy scores (undocumented endpoints, behind feature flag)
- **[Moxfield](https://www.moxfield.com)** -- Public decklists and deck search (reverse-engineered API, behind feature flag)
- **[Spicerack](https://spicerack.gg)** -- Tournament results and standings ([documented API](https://docs.spicerack.gg))
- **[MTGGoldfish](https://www.mtggoldfish.com)** -- Competitive metagame data, archetypes, format staples (HTML scraping, behind feature flag)

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for full license texts and usage terms.

## Disclaimer

mtg-mcp-server is unofficial Fan Content permitted under the [Fan Content Policy](https://company.wizards.com/en/legal/fancontentpolicy). Not approved/endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast. &copy; Wizards of the Coast LLC.

## License

MIT -- see [LICENSE](LICENSE)
