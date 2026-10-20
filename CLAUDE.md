# MTG MCP Server

Unified MCP server providing Magic: The Gathering data to AI assistants. Composes Scryfall, Commander Spellbook, 17Lands, EDHREC, Moxfield, Spicerack and MTGGoldfish into one server using FastMCP 3.x's provider/mount architecture.

Stack: Python 3.12+ · FastMCP 3.2.x · httpx · Pydantic v2 · structlog. Tooling: mise · uv · ruff · ty · pytest · respx. Prerequisite: [mise](https://mise.jdx.dev); `mise install` gets everything else.

## Commands

```bash
mise run setup            # Install deps, create venv
mise run check            # Quality gate: lint + typecheck + all tests except live (~3min)
mise run check:quick      # lint + typecheck + only tests affected by recent changes (~10s*)
mise run check:full       # check + live tests (~4-5min). CI runs this on PRs
mise run test             # All tests except live, with coverage
mise run test:quick       # Affected tests only, via pytest-testmon (~5s*)
mise run test:unit        # Services + providers (~2.5min)
mise run test:integration # Full orchestrator, fixture-mocked backends (~2s)
mise run test:live        # Real server + real APIs (~1-2min)
mise run lint             # ruff check + ruff format --check
mise run typecheck        # ty check
mise run fix              # Auto-fix lint and format
mise run dev              # fastmcp dev inspector (MCP Inspector on :6274)
mise run serve            # Run server via stdio
```

*testmon is fast when nothing changed; after changes it may approach full-suite time.

**Which tier:**
- Service or provider change: `test:quick` while iterating, `check` before commit.
- Data parsing, models or fixtures: `test:quick` → `test:integration` → `test:live` (data bugs hide in real-world data).
- Workflows: `test:quick` is enough (AsyncMock, no HTTP).
- Before any PR: `check`, plus `test:live` for data-layer PRs.

**CI:** PRs to main run `check` + `live-tests` + `build` + `security` in parallel. Pushes to main skip live tests (already validated on the PR).

## Conventions

Architecture and patterns: @docs/ARCHITECTURE.md (layers, client lifecycle, error flow, testing tiers, decisions).

- TDD: write the failing test first. Tests use respx against fixtures in `tests/fixtures/` (captured real JSON). Never hit live APIs outside `tests/live/`.
- Modern typing (`list[str]`, `str | None`); zero ty errors; no `Any`, use `Unknown` or proper types.
- structlog everywhere, one bound logger per service, logging to stderr.
- Services raise typed exceptions. Providers and `workflows/server.py` convert them with `raise ToolError("<actionable message>") from exc` (`fastmcp.exceptions`, B904); never construct `is_error` by hand.
- Workflows are pure async functions (no MCP imports) that handle partial failure. Test them with `unittest.mock.AsyncMock`, not respx.
- Optional numeric fields: use `is not None`, never truthiness (`0`/`0.0` are valid).
- Pydantic v2: `.model_validate()`, not `.parse_obj()`.
- Every service method uses `@async_cached` with a class-level `TTLCache`. Add each new cache to the autouse `_clear_caches` fixture in `tests/conftest.py`.
- Fragile sources sit behind flags: EDHREC (`MTG_MCP_ENABLE_EDHREC`, undocumented endpoints, will break), MTGGoldfish (`MTG_MCP_ENABLE_MTGGOLDFISH`, HTML scraped with selectolax), Moxfield. Bulk data (`MTG_MCP_ENABLE_BULK_DATA`) is a lazy-loading, file-based service (not a `BaseClient`) that returns full `Card` objects.
- Integration tests: `@pytest.mark.integration`, included in `check`. Live tests: `@pytest.mark.live`, skipped by default.

## Gotchas

- Import `from fastmcp import FastMCP`, not `from mcp.server.fastmcp`.
- The CLI needs the subcommand: `fastmcp dev inspector <file>`, not `fastmcp dev <file>`.
- Use the shared `TOOL_ANNOTATIONS` from `mtg_mcp_server.providers`, never inline `ToolAnnotations()`.
- Service clients: lifespan + module-level `_client`, constructed with `Settings()` so `MTG_MCP_*_BASE_URL` is honoured. Not `Depends()`/`ctx.lifespan_context`, which don't propagate through `mount()`.
- The workflow lifespan uses `AsyncExitStack`; provider lifespans use `async with client:`. `BaseClient.__aenter__` returns `Self` so the subclass type is inferred.
- Scryfall requires `User-Agent` and `Accept` headers on every request.
- 17Lands rate-limits aggressively (1 req/s max); cache everything.
- Always `uv run python3`, never bare `python3`.
- `Client.call_tool()` returns a `CallToolResult` (not subscriptable): read `.content[0].text`. For error tests, pass `raise_on_error=False` and check `.is_error`.

## Git workflow

- Work on a feature branch (`feat/description`); never commit to main. Commit atomically per logical unit.
- Before launching worktree agents: commit everything, then confirm `git status` is clean **and** `git branch` shows the right feature branch. Agents branch from the last commit on the current branch. After launch, verify the worktrees are based on the right commit.
- Worktree agents rewrite whole files. Never `cp` a worktree file over a scaffolded one: diff first or merge selectively. Cherry-pick agent commits, discard agent rewrites of shared files, then run `git diff <prior-commit>..HEAD -- <shared-files>` to confirm nothing was reverted.
- Cancel stale CI runs on the branch before pushing new commits.

## Agent dispatch

Use the most parallel approach that fits:
1. **Parallel agents** (`superpowers:dispatching-parallel-agents`) for independent file domains, e.g. plan phases with exclusive-file agent tables.
2. **Subagent-driven development** (`superpowers:subagent-driven-development`) for dependent sequential tasks: a fresh subagent per task with a two-stage review (spec compliance, then code quality).
3. **Sequential** only when tasks share files that can't be split.

Commit before launching worktree agents.

## PRs

Always open as drafts (`gh pr create --draft`).

Handling review comments:
1. Fetch them: `gh api /repos/{owner}/{repo}/pulls/{number}/comments`.
2. Assess each one (fix, or defer and why) and reply via `gh api .../comments/{id}/replies`.
3. Make the fixes and run `mise run check`.
4. Commit referencing the PR, then push.
5. Resolve threads with the GraphQL `resolveReviewThread` mutation (thread IDs from `repository.pullRequest.reviewThreads`).

### Review checklist

**New provider/backend:**
- [ ] `docs/TOOL_DESIGN.md`: tool rows, resources
- [ ] `docs/ARCHITECTURE.md`: system diagram, structure, counts, decisions log
- [ ] `docs/SERVICE_CONTRACTS.md`: summary-table row (URL, auth, rate limit, flag, stability) + endpoints and quirks
- [ ] `docs/CACHING_DESIGN.md`: TTL rows for new service methods
- [ ] `docs/DATA_SOURCES.md`: status row
- [ ] `.claude/skills/smoke-test/SKILL.md`: new steps, updated totals
- [ ] `tests/integration/conftest.py`: respx mocks; `tests/integration/test_orchestrator_e2e.py`: tool count
- [ ] `tests/test_parameter_descriptions.py`: provider in the parametrize list
- [ ] `server.py`: mount + instructions string

**Error handling:** `ToolError ... from exc`; typed exceptions only, no broad `except Exception`; workflows return partial data; no silent default fallback without structlog context.

**Data integrity:** `is not None` for optional numerics; new caches use `@async_cached` + clearing in `tests/conftest.py`; `.model_validate()`.

## Status

All backends are implemented; none are stubbed. 69 tools (incl. `ping`), 19 prompts, 21 resource templates. History: `CHANGELOG.md`.

## Environment

Copy `.env.example` to `.env`. All values have defaults and no credentials are needed (all APIs are public). Every setting uses the `MTG_MCP_` prefix.

## Key references

- @docs/ARCHITECTURE.md: architecture, FastMCP patterns, decisions
- @docs/TOOL_DESIGN.md: tools, prompts, resources
- @docs/SERVICE_CONTRACTS.md: per-backend endpoints, auth, rate limits, quirks, flags
- @docs/DATA_SOURCES.md: sources evaluated, stability, status
- @docs/CACHING_DESIGN.md: TTL strategy, per-method TTLs, bulk data layer
