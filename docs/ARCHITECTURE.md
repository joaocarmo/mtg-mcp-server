# MTG MCP Server — Architecture

A unified MCP server that exposes Magic: The Gathering data to AI assistants. Each data source is its own FastMCP sub-server, mounted on one orchestrator under a namespace. Workflow tools combine several sources and are mounted without a namespace.

**Principles:** independent backends behind one interface; fixture-driven TDD (respx, never live APIs); structlog with bound context everywhere; FastMCP's native OpenTelemetry traces every tool call.

---

## 1. System

```
MCP client (Claude Code / Desktop / any) ── stdio
                     │
        MTG Orchestrator — FastMCP("MTG"): 66 tools, 19 prompts, 20 resource templates
                     │
   ├── Workflows (no namespace) — commander, draft/limited, deck building,
   │     constructed/metagame, sideboard, rules engine (see TOOL_DESIGN.md)
   ├── scryfall_   → api.scryfall.com            card data, prices, rulings, sets
   ├── bulk_       → Scryfall Oracle bulk file    rate-limit-free lookup/search
   ├── spellbook_  → backend.commanderspellbook   combos, bracket estimation
   ├── draft_      → 17lands.com                  card win rates, archetype stats
   ├── edhrec_     → json.edhrec.com (scraped)    commander staples, synergy
   ├── moxfield_   → api2.moxfield.com (rev-eng)  decklists, deck/user search
   └── goldfish_   → mtggoldfish.com (HTML)       metagame, archetypes, staples, prices
```

Per-backend endpoints, rate limits and feature flags: [SERVICE_CONTRACTS.md](SERVICE_CONTRACTS.md).

## 2. Stack

| Layer | Tool | Notes |
|-------|------|-------|
| Task runner | mise | Installs Python, uv, ruff, ty; runs all dev tasks (`mise.toml`) |
| Language / packages | Python 3.12+, uv | |
| MCP framework | fastmcp 3.2.x | Provider/mount architecture |
| Type check / lint | ty (beta), ruff | |
| HTTP / models / settings | httpx, Pydantic v2, pydantic-settings | |
| Retries / logging / caching | tenacity, structlog, cachetools | |
| HTML parsing | selectolax | MTGGoldfish only; 10-50x faster than BeautifulSoup |
| Testing | pytest, pytest-asyncio, respx, pytest-cov, pytest-testmon | |

## 3. Project structure

```
src/mtg_mcp_server/
├── server.py        # Orchestrator: mounts providers, middleware, stdio entry point
├── config.py        # Settings (pydantic-settings, MTG_MCP_ prefix)
├── types.py         # Shared Pydantic models (services return, tools consume)
├── logging.py
├── services/        # Async API clients — NO MCP awareness. base.py, cache.py, one file per backend
├── providers/       # One FastMCP sub-server per backend, independently runnable.
│                    #   __init__.py: TOOL_ANNOTATIONS, tag constants, ATTRIBUTION_* strings
├── utils/           # Pure helpers: color identity, decklist parsing, format rules, formatters,
│                    #   mana, fuzzy matching, query parser, slim.py (slim structured_content dicts)
└── workflows/       # Pure async functions per domain + server.py (wraps them as tools, prompts,
                     #   resources). card_resolver.py: bulk-data-first lookup, Scryfall fallback
tests/               # Mirrors src/: services/, providers/, workflows/, utils/,
                     #   integration/ (fixture-mocked E2E), live/ (real APIs), fixtures/ (captured responses)
```

**Services vs providers:** services are plain async classes that call external APIs and raise typed exceptions; providers register tools on top of them. **Workflows** are pure async functions that take service clients as keyword arguments and return `WorkflowResult` (markdown + data). They have zero MCP imports: `workflows/server.py` wraps them and converts exceptions to `ToolError`. That avoids circular imports and lets tests use `AsyncMock`.

## 4. FastMCP patterns

**Mounting** (`server.py`): `mcp.mount(scryfall_mcp, namespace="scryfall")` prefixes tools (`search_cards` → `scryfall_search_cards`). Feature-flagged backends mount conditionally. `mcp.mount(workflow_mcp)` mounts without a namespace. Each mounted server's lifespan runs when the parent starts.

**Client lifecycle:** each provider creates its client in a `@lifespan`, constructed from `Settings()` so `MTG_MCP_*_BASE_URL` overrides apply. The client is stored in a module-level `_client` and read through `_get_client()`, which raises `RuntimeError` if the lifespan isn't running. `Depends()`/`ctx.lifespan_context` do **not** propagate through `mount()` in FastMCP 3.2.x, so the module-level variable is the workaround. See `providers/scryfall.py` for the template.

**Workflow lifespan** uses `AsyncExitStack` to enter several clients, skipping disabled backends (those stay `None` and workflows degrade). `BaseClient.__aenter__` returns `Self` so `enter_async_context()` infers the subclass. The bulk client starts `start_background_refresh()`, and the rules service calls `ensure_loaded()`.

**Tools** return `ToolResult(content=markdown, structured_content=data)`. All share `TOOL_ANNOTATIONS` (readOnly, idempotent, openWorld) plus domain `tags`. Long-running workflows report progress through an `on_progress` callback, which `server.py` bridges to `ctx.report_progress()`.

**Resources** use `mtg://` URI templates on the providers and the workflow server. **Prompts** are registered on the workflow server.

**Response size:** heavy tools get `ResponseLimitingMiddleware(max_size=30_000)`, with a global `100_000` safety net. The main control is slim field sets plus `limit` parameters.

**Transport:** stdio only; the client launches the server as a local subprocess.

## 5. Service layer

All HTTP clients extend `BaseClient`: an `httpx.AsyncClient` with configurable timeouts, rate limiting (semaphore + inter-request delay), tenacity retries with exponential backoff on 429/5xx, and a bound structlog logger. Bulk data and Comprehensive Rules are file-based services, not `BaseClient` subclasses.

**Errors:**
- Services raise typed exceptions and never format for MCP.
- Providers catch them and raise `ToolError(...) from exc`; FastMCP sets `is_error`. All servers (orchestrator, providers, workflows) use `mask_error_details=True` to hide unexpected internals.
- Workflows tolerate partial failure: if an optional backend is down or disabled, they return what they can and note the gap.

**Logging:** `structlog.get_logger(service=...)`, debug events like `search` / `search.complete`, always to stderr (stdout is the MCP transport in stdio mode).

**Configuration:** `config.py` / `.env.example`. Every setting uses the `MTG_MCP_` prefix and has a sensible default; no credentials are needed.

## 6. Testing

| Tier | Location | What |
|------|----------|------|
| Unit | `tests/{services,providers,utils,workflows}/` | respx + fixtures for HTTP; providers through `fastmcp.Client(transport=server)` in-memory; workflows with `AsyncMock` |
| Integration | `tests/integration/` | Full orchestrator with all backends respx-mocked; catches registration/namespacing issues. `@pytest.mark.integration` |
| Live | `tests/live/` | Real server subprocess over stdio, real APIs; catches data quirks that fixtures miss. `@pytest.mark.live`, skipped by default |

`Client.call_tool()` returns a `CallToolResult`: read `.content[0].text`; for error cases pass `raise_on_error=False` and check `.is_error`. Commands and gates: see CLAUDE.md / CONTRIBUTING.md.

## 7. Decisions log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Framework | FastMCP 3.2.x | Native composition, provider architecture, OTEL, annotations |
| Architecture | Single server, mounted sub-servers | Independent testability + single deployment |
| Transport | stdio only, run locally | Claude Code/Desktop launch it as a subprocess; no hosted deployment to maintain |
| Type checker | ty (beta) | Astral stack, speed |
| HTTP mocking | respx | Clean async httpx mocking |
| Namespaces | `scryfall_`, `bulk_`, `spellbook_`, `draft_`, `edhrec_`, `moxfield_`, `goldfish_`; workflows unprefixed | Avoid collisions; clean workflow names |
| Client lifecycle | Lifespan + module-level `_client` | `Depends()`/`lifespan_context` break through `mount()` |
| Settings wiring | `Settings()` in each lifespan | Base URLs overridable via env |
| Errors | `ToolError` from `fastmcp.exceptions` | FastMCP handles `is_error` conversion |
| Tool metadata | Shared `TOOL_ANNOTATIONS` + tag constants | All tools read-only/idempotent; tags group by domain (commander, draft, pricing, beta, …) |
| Workflow architecture | Pure functions + wiring layer, tested with `AsyncMock` | No circular imports, no HTTP layer to mock |
| Multi-client lifespan | `AsyncExitStack` | Cleaner than nested `async with` with feature flags |
| Service caching | cachetools `TTLCache` per method | Caches parsed models; per-method TTL (see [CACHING_DESIGN.md](CACHING_DESIGN.md)) |
| Bulk data | Scryfall Oracle Cards, file-based service, replaced MTGJSON | Same `Card` shape as the API, plus prices, legalities, images and EDHREC rank that MTGJSON lacked |
| Bulk integration | Workflow layer via `card_resolver.py`, not inside `ScryfallClient` | Keeps services independent; one shared bulk-first/API-fallback path |
| Rules engine | Local file-based `RulesService` in the workflow lifespan | Rules tools compose with bulk data for card examples |
| Structured output | `ToolResult` with `structured_content`; slim dicts in `utils/slim.py` | Programmatic consumption at bounded size; full data via resource URIs |
| Response format | `response_format: "detailed" \| "concise"` | Controls verbosity without duplicate tools |
| Response limiting | Per-tool 30k middleware + global 100k | Safety net behind slim fields and limits |
| Attribution | `ATTRIBUTION_*` constants appended to output | Data-source compliance |
| Fragile sources | EDHREC, Moxfield, MTGGoldfish behind flags, tagged beta, cached aggressively | Undocumented/scraped; can break without notice |
| HTML parsing | selectolax | Fast, tiny; used only by `services/mtggoldfish.py` |
| CodeMode | Experimental, `enable_code_mode` flag | FastMCP transform replacing tools with discovery/execute meta-tools at 40+ tools |
| Parallel development | Worktree agents on exclusive files; shared files scaffolded first | Agents rewrite whole files; see CLAUDE.md Git Workflow |
