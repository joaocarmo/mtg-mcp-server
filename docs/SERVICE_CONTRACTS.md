# MTG MCP Server: Service Contracts

Endpoints, auth, rate limits and response quirks for each backend. Full response shapes are in the captured fixtures under `tests/fixtures/<service>/`. Cache TTLs: [CACHING_DESIGN.md](CACHING_DESIGN.md).

## Summary

| Service | Base URL | Auth / headers | Rate limit | Flag (`MTG_MCP_…`) | Stability |
|---------|----------|----------------|------------|--------------------|-----------|
| Scryfall | `api.scryfall.com` | `User-Agent: mtg-mcp-server/<version>` + `Accept: application/json` required | 10 req/s (100ms delay) | always on | Official, solid |
| Scryfall bulk | via `/bulk-data` | none | n/a (file) | `ENABLE_BULK_DATA` | Official, solid |
| Spellbook | `backend.commanderspellbook.com` | none | undocumented; ~3 req/s, back off on 429 | always on | Official, open source (MIT) |
| 17Lands | `www.17lands.com` | none | 1 req/s max, aggressive limiting | `ENABLE_17LANDS` | Unofficial, stable for years |
| EDHREC | `json.edhrec.com` | none | self-imposed 0.5 req/s | `ENABLE_EDHREC` | Reverse-engineered, fragile |
| Moxfield | `api2.moxfield.com` | `User-Agent: mtg-mcp-server/<version>` | self-imposed 1 req/s | `ENABLE_MOXFIELD` | Reverse-engineered, fragile |
| MTGGoldfish | `www.mtggoldfish.com` | browser-like UA (403 otherwise) | self-imposed 0.5 req/s | `ENABLE_MTGGOLDFISH` | HTML scraping, fragile |
| TopDeck.gg | `topdeck.gg/api` | `Authorization: <key>` (free key, per user) | 100 req/min (bulk search lower, unpublished); client 1.5 req/s | key set (`TOPDECK_API_KEY`) | Official, documented |
| Comp. Rules | `media.wizards.com/…/MagicCompRules%20<date>.txt`, discovered from `magic.wizards.com/en/rules` (fallback `RULES_URL`) | none | n/a (file) | `ENABLE_RULES` | Official |

Every base URL can be overridden with `MTG_MCP_<SERVICE>_BASE_URL`. When a flag is off, that provider isn't mounted and workflows treat the backend as unavailable. Fragile sources follow one pattern: feature flag, beta tag, aggressive caching, defensive parsing (`isinstance`/`.get()` chains plus structlog warnings), and `ToolError` on failure, so they never crash the orchestrator.

---

## Scryfall

Docs: https://scryfall.com/docs/api · syntax: https://scryfall.com/docs/syntax

| Endpoint | Notes |
|----------|-------|
| `GET /cards/named?exact=` / `?fuzzy=` | Single card; 404 if not found |
| `GET /cards/search?q=&page=` | `{total_cards, has_more, data: [card]}` |
| `GET /cards/{id}` | By UUID |
| `GET /cards/{id}/rulings` | `{data: [{source, published_at, comment}]}` |
| `GET /sets`, `GET /sets/{code}` | Set metadata |

Useful syntax: `f:commander`, `id:sultai` / `id<=sultai`, `t:creature`, `o:"whenever"`, `usd<5`. Card fields used: name, mana_cost, cmc, type_line, oracle_text, colors, color_identity, keywords, power/toughness, set, rarity, prices (usd/usd_foil/eur, strings), legalities, image_uris, edhrec_rank (fixture: `card_muldrotha.json`).

**Terms:** do not paywall Scryfall data; do not simply republish it, add value instead; do not crop or distort images, and keep the artist/copyright visible.

## Scryfall bulk data

Docs: https://scryfall.com/docs/api/bulk-data. `/bulk-data` lists the files; the `oracle_cards` entry is one object per unique card, **same shape as the API**, so the same `Card` model parses both. It updates daily.

`ScryfallBulkClient` (file-based):
- Downloads lazily on first access, not at startup.
- Parses into a `dict[str, Card]` keyed by lowercase name.
- Filters out non-playable layouts (art_series, token, double_faced_token, emblem, vanguard, planar, scheme, augment, host) so they can't overwrite real cards.
- Refreshes in the background every `BULK_DATA_REFRESH_HOURS` (12h); if a refresh fails, it keeps serving the stale data.

Methods: `get_card`, `get_cards`, `search_cards` (name substring), `search_by_type`, `search_by_text`, `filter_cards(**criteria)`.

## Commander Spellbook

Docs: `/schema/swagger/` · syntax: https://commanderspellbook.com/syntax-guide/ · source: https://github.com/SpaceCowMedia/commander-spellbook-backend

| Endpoint | Notes |
|----------|-------|
| `GET /variants/?q=card:"Muldrotha" coloridentity:sultai` | Aliases: `card:`/`cards:`, `coloridentity:`/`color`/`ci`/`id`; also `commander:`, `bracket:`, `popularity:`, `legal:`. Paginates with `limit`/`offset`, not `page` |
| `GET /variants/{id}/` | Single combo |
| `POST /estimate-bracket` | Body `{"commanders": [{"card", "quantity"}], "main": [...]}` (plain text with `// Commander` headers also accepted). Returns `bracketTag`, `bannedCards`, `gameChangerCards`, mass-land-denial / extra-turn / lock / control / skip-turn combos, `twoCardCombos` |
| `POST /find-my-combos` | Same body; returns `included`, `almostIncluded`, `almostIncludedByAddingColors` |

Combo variant quirks (fixture: `combo_detail.json`):
- `zoneLocations` codes: B=Battlefield, H=Hand, G=Graveyard, E=Exile, L=Library, C=Command zone.
- `produces` items are `{"feature": {...}, "quantity": N}`.
- `of` holds only combo IDs. Prerequisites and steps are flattened into `easyPrerequisites`, `notablePrerequisites` and `description`.
- `bracketTag` is a single letter (e.g. `"E"`), shown raw. No mapping to brackets 1-4 is implemented.

## 17Lands

Public datasets: https://www.17lands.com/public_datasets · usage guidelines: https://www.17lands.com/usage_guidelines

| Endpoint | Notes |
|----------|-------|
| `GET /card_ratings/data?expansion=&event_type=&start_date=&end_date=` | `event_type` is canonical (legacy alias `format` works here only). Dates are optional, but without them `avg_pick` (and sometimes `play_rate`) is null |
| `GET /color_ratings/data?expansion=&event_type=&start_date=&end_date=` | Dates **required** (HTTP 400 without them). Rows: `{is_summary, color_name, short_name, wins, games}`; win rate = `wins / games`. Includes mono through five-colour, splash and summary rows |

Metric mapping: **GIH WR** = `ever_drawn_win_rate` (best single quality metric), **ALSA** = `avg_seen` (lateness, a signal of openness), **OH WR** = `opening_hand_win_rate`, **IWD** = `drawn_improvement_win_rate`.

Caveats: cards with fewer than 500 games have no win-rate data. 17Lands users skew above average, so the baseline is ~56%, not 50%. 17Lands uses Arena card names.

## EDHREC

Undocumented internal JSON (community reference: `pyedhrec`).

| Endpoint | Notes |
|----------|-------|
| `GET /pages/commanders/{slug}.json` | Slug: lowercase, hyphens, no commas or apostrophes (`muldrotha-the-gravetide`) |
| `GET /pages/cards/{slug}.json` | Card page |

Cards live at `container.json_dict.cardlists[].cardviews[]` with `name`, `sanitized`, `synergy` (-1.0 to 1.0: specific to this commander, not just popular), `inclusion` (% of decks), `num_decks`, `label`. Each list has a category `header` (Creatures, Lands, …).

## Moxfield

Reverse-engineered; no stability guarantees.

| Endpoint | Notes |
|----------|-------|
| `GET /v3/decks/all/{deck_id}` | Metadata plus per-board card maps (`commanders`, `mainboard`, `sideboard`, `companions`). The client accepts a full URL or a bare ID |
| `GET /v2/decks/search` | `pageNumber` (1-indexed), `pageSize` (20), `sortType` Updated/Created/Views, `sortDirection`, `q`, `fmt` (lowercase format). Returns `{pageNumber, pageSize, totalResults, totalPages, data: [deck summary]}` |
| `GET /v2/users/search-sfw?filter=` | `{data: [{userName, displayName, badges}]}` |

Errors: `MoxfieldError(ServiceError)`, which is also raised on non-dict responses.

## MTGGoldfish

No API (JSON requests return 406). Parsed with selectolax.

| Endpoint | Parsed from |
|----------|-------------|
| `GET /metagame/{format}/full` (lowercase slug) | `.archetype-tile`: name `.archetype-tile-title a`, slug from its href, meta % and deck count from the 1st/2nd `.archetype-tile-statistic-value`, price `.price-tag-paper-price`, colours from `.mana-icon` classes `ms-w/u/b/r/g` |
| `GET /archetype/{format}-{slug}` | Metadata from `.deck-container-information`; deck ID by regex from the `initializeDeckComponents('guid', '{deck_id}', …)` JS call |
| `GET /deck/download/{deck_id}` | **Plain text** `4 Card Name` lines; a blank line separates main from sideboard |
| `GET /format-staples/{format}` | Table rows: rank, card name (`td a`), % of decks, avg copies |

Errors: `MTGGoldfishError` → `FormatNotFoundError`, `ArchetypeNotFoundError`.

## TopDeck.gg

Documented v2 API ([docs](https://topdeck.gg/docs/tournaments-v2), [OpenAPI](https://topdeck.gg/openapi.json)). Terms: [Developer Terms](https://topdeck.gg/developer-terms). They require a visible credit with a link wherever users see the data, and forbid compiling data about individual players.

| Endpoint | Notes |
|----------|-------|
| `POST /v2/tournaments` | Query mode: `game` + `format` (both case sensitive), `last` (days), `participantMin`, `columns`. TID mode: `{"TID": …}`. Completed tournaments only; an unknown TID returns `200 []`. Standings come in final rank order (checked against `/standings`). `leader` (commander formats) or `archetype` (others, once decklists are public) arrive without a column request |
| `GET /v2/tournaments/{TID}/players/{ID}` | Swiss record (`gamesWon` etc.), `winsBracket`/`lossesBracket`, `decklist` text, `deckObj`. 404 `{"error": "Player not found in tournament"}` |

Quirks seen live (28 October 2026):
- Searches include organisers' test events dated years ahead. The client drops events that have not started.
- `decklist` text has literal `\n` and `\'` escapes. `deckObj` is `{section: {card name: {id, count}}}` plus a `metadata` entry, which the model drops.
- About half of EDH entries have no `leader` (no deck submitted).
- `/info` returns `endDate` in milliseconds but `startDate` in seconds (unused).
- Responses carry no rate-limit headers. A 30-day EDH search (16+ players) is about 1.8 MB and takes about 2 s.
- `/standings` includes every decklist once an event ends (1.5 MB for 150 players), so the client uses TID mode instead.

Errors: `TopDeckError(ServiceError)` → `TournamentNotFoundError` (empty TID result or player 404). The provider maps 401 to a message naming `MTG_MCP_TOPDECK_API_KEY`.

## Comprehensive Rules

Plain-text file, updated about 4 times a year. `RulesService` (file-based) downloads it lazily and parses it into:
- a rules index (`"704.5k"` → `Rule{number, text, parent_number, subrules}`)
- a glossary (lowercase term → definition)
- a sections index (`"7"` → "Additional Rules")

Each load finds the current TXT link on `magic.wizards.com/en/rules`; if that fails, it falls back to `RULES_URL` and logs `rules.discovery_failed`. It tracks the 702.x keyword rules. It refreshes after `RULES_REFRESH_HOURS` (168h); if a refresh fails, it keeps serving the stale data. Methods: `lookup_by_number`, `search_rules(query, section)`, `glossary_lookup`, `list_keywords`, `list_sections`. When disabled, rules tools raise `ToolError` and nothing is downloaded.
