# Contributing to MTG MCP Server

## Setup

Requires [mise](https://mise.jdx.dev) and Git; mise installs Python, uv, ruff and ty.

```bash
git clone https://github.com/joaocarmo/mtg-mcp-server.git
cd mtg-mcp-server
mise install
mise run setup     # venv + dependencies
mise run check     # verify: lint + typecheck + tests
```

## Workflow

Work test-first. Write a failing test against a fixture or mock, then implement. Iterate with `mise run test:quick`, which re-runs only the affected tests (pytest-testmon). Run `mise run check` before you open a PR.

| Command | Purpose |
|---------|---------|
| `mise run test:quick` | Only tests affected by your edits |
| `mise run test` | All tests except live, with coverage |
| `mise run test:integration` / `test:live` | Fixture-mocked orchestrator E2E / real server against real APIs |
| `mise run check` | Lint + typecheck + tests (the quality gate) |
| `mise run check:full` | `check` + live tests (what CI runs on PRs) |
| `mise run lint` / `typecheck` / `fix` | ruff check + format check / ty / auto-fix |
| `mise run dev` | MCP Inspector on :6274 |
| `mise run serve` | Run the server over stdio |

## Code style

- ruff for lint and format; ty for type checking.
- Modern typing (`list[str]`, `str | None`); no `Any`, use proper types.
- structlog with bound context, logging to stderr (stdout is the MCP transport in stdio mode).
- Optional numeric fields: check `is not None`, never truthiness (`0` and `0.0` are valid).

## Testing

- **Services:** mock httpx with [respx](https://github.com/lundberg/respx) against fixtures in `tests/fixtures/` (captured real responses). Only `tests/live/` calls real APIs.
- **Providers:** `fastmcp.Client(transport=server)` in memory.
- **Workflows:** `unittest.mock.AsyncMock` clients (workflows are pure functions).
- Copy the pattern from an existing test in the matching `tests/` subdirectory.
- Coverage minimum is 80%, enforced by CI.

## Error handling

- Services raise typed exceptions (e.g. `CardNotFoundError`, `ScryfallError`).
- Providers catch them and `raise ToolError(...) from exc` (`fastmcp.exceptions`).
- Workflows handle partial failure: if one backend is down, return what you can.

## Pull requests

1. Branch from `main`.
2. Make changes with tests, and make sure `mise run check` passes.
3. Open the PR with a summary (what and why), a test plan, and confirmation that checks pass and coverage held.

Architecture and the rest of the docs: [docs/README.md](docs/README.md). Questions: open a GitHub issue.
