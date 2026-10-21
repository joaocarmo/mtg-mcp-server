# MTG MCP Server — Caching Design

Two layers: per-method **TTL caches** on every service method (deduplicate repeated calls within a session) and **Scryfall bulk data** (cold-start and rate-limit-free card data).

## TTL caches

Each service method gets a class-level `cachetools.TTLCache` through `@async_cached(cache, key=...)` (`services/cache.py`).

**Why cachetools:**
- It caches parsed Pydantic models, so a hit skips both the network and parsing.
- TTLs can be set per method.
- An HTTP-level cache (Hishel) was rejected: it caches raw bytes that need re-parsing, and most of these APIs send no `Cache-Control` headers anyway.

**Why no locks:** everything runs on a single asyncio loop, and the per-service rate limiter already serialises cold-cache stampedes.

**Key functions:**
- `cachetools.keys.methodkey` (default) skips `self`, so entries are keyed on arguments, not instance identity.
- `_decklist_key` converts positional and keyword `list` args to tuples (lists are unhashable). Spellbook's POST methods use it: they are read-only queries, so caching them is correct.

**Lifecycle:**
- Caches are class-level. Each client is a lifespan singleton, so this is effectively per-instance.
- Caches live for the server's lifetime; nothing is persisted, and a cold start costs one call per unique query.
- Disabled backends never populate their caches.
- `MTG_MCP_DISABLE_CACHE=true` calls `disable_all_caches()`, a module-level kill switch that turns `@async_cached` into a no-op.

| Service | Method | TTL | Maxsize | Rationale |
|---------|--------|-----|---------|-----------|
| Scryfall | `get_card_by_name` | 24h | 500 | Oracle text, types and colours almost never change |
| Scryfall | `search_cards` | 1h | 100 | Result sets change as cards are added |
| Scryfall | `get_rulings` | 24h | 200 | Rarely change |
| Scryfall | `get_sets` / `get_set` | 24h | 50 | Static after release |
| Spellbook | `find_combos` | 24h | 200 | Combos rarely added |
| Spellbook | `get_combo` | 24h | 100 | Static once created |
| Spellbook | `find_decklist_combos` | 12h | 50 | User iterates on the decklist |
| Spellbook | `estimate_bracket` | 12h | 50 | Same as above |
| 17Lands | `card_ratings` | 4h | 20 | Volatile in a set's first week, then stable; 4h balances freshness vs rate limit |
| 17Lands | `color_ratings` | 4h | 20 | Same lifecycle |
| EDHREC | `commander_top_cards` | 24h | 100 | EDHREC aggregates daily |
| EDHREC | `card_synergy` | 24h | 200 | Same cycle |
| Moxfield | `get_deck` | 4h | 100 | Lists are stable within a session |
| Moxfield | `search_decks` | 1h | 50 | New decks posted constantly |
| Moxfield | `search_users` | 4h | 100 | Rarely changes |
| MTGGoldfish | `get_metagame` | 6h | 50 | Shares shift slowly; limits scraping load |
| MTGGoldfish | `get_archetype` | 12h | 100 | Sample lists stable once posted |
| MTGGoldfish | `get_format_staples` | 12h | 50 | Rankings shift slowly |

TTLs are hardcoded class constants because they reflect upstream data staleness, not deployment config. Maxsize values are conservative working-set estimates. Adaptive TTLs (e.g. 1h for 17Lands in a set's first week) were considered and rejected as not worth the complexity.

- **Moxfield `get_deck`** uses a custom key (`_moxfield_deck_key`) that normalises URLs to deck IDs, so a URL and a bare ID share an entry.
- **EDHREC `card_synergy`** delegates to `commander_top_cards` and scans the result. Both are cached independently, so they can briefly diverge (worst case: synergy up to 24h stale). That's acceptable, since both come from the same daily aggregation.

**Testing:**
- The autouse `_clear_caches` fixture in `tests/conftest.py` must clear every new cache.
- Cache tests check that the first call hits the API and the second doesn't, and that different arguments (e.g. `fuzzy=True` vs `False`) get separate entries.
- Workflow tests use `AsyncMock` clients, which bypass caching.

## Scryfall bulk data

Service details (lazy download, layout filtering, 12h background refresh, stale-on-failure): [SERVICE_CONTRACTS.md](SERVICE_CONTRACTS.md#scryfall-bulk-data). Behind `MTG_MCP_ENABLE_BULK_DATA`.

It's used in three ways:
1. The `bulk_` provider: rate-limit-free lookup, search, legality, staples, ban lists, similar and random cards.
2. A separate `ScryfallBulkClient` instance in the workflow lifespan.
3. `workflows/analysis.py` (`deck_analysis`): checks bulk data first and falls back to the Scryfall API, which then populates the TTL cache.

Provider-level `scryfall_` tools always hit the API (TTL-cached). When the flag is off, the provider isn't mounted and workflows go straight to the API.
