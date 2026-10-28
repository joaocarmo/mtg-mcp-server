# mtg-mcp-server

An MCP server that gives AI assistants Magic: The Gathering data: cards, prices, rules, combos, draft stats, Commander and constructed metagame, and deck-building tools. It runs locally over stdio. It works without an API key; only the optional TopDeck.gg tools need one.

## Install

Requires [uv](https://docs.astral.sh/uv/).

**Claude Code**

```bash
claude mcp add mtg -- uvx --from git+https://github.com/joaocarmo/mtg-mcp-server mtg-mcp-server
```

**Claude Desktop** (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "mtg": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/joaocarmo/mtg-mcp-server", "mtg-mcp-server"]
    }
  }
}
```

**From a clone**

```bash
git clone https://github.com/joaocarmo/mtg-mcp-server.git
claude mcp add mtg -- uv run --directory /path/to/mtg-mcp-server mtg-mcp-server
```

## Update

uvx caches the build, so it keeps running the version it first installed. To get the latest `main`, run:

```bash
uvx --refresh --from git+https://github.com/joaocarmo/mtg-mcp-server mtg-mcp-server
```

This starts the server, which then waits for input. Stop it with Ctrl-C and restart your MCP client. From a clone, run `git pull` instead.

## Configuration

Settings are `MTG_MCP_` environment variables, all with working defaults (see `.env.example`). To turn off a backend, set `MTG_MCP_ENABLE_<NAME>=false`, where `<NAME>` is `17LANDS`, `EDHREC`, `MOXFIELD`, `MTGGOLDFISH`, `BULK_DATA` (skips a ~30 MB download) or `RULES`.

```bash
claude mcp add mtg -e MTG_MCP_ENABLE_EDHREC=false -- uvx --from git+https://github.com/joaocarmo/mtg-mcp-server mtg-mcp-server
```

### TopDeck.gg (optional)

The `topdeck_` tools give tournament results, decklists and the cEDH metagame from [TopDeck.gg](https://topdeck.gg). They need a free API key from the [developer portal](https://topdeck.gg/developers), and appear only when it is set:

```bash
claude mcp add mtg -e MTG_MCP_TOPDECK_API_KEY=<your key> -- uvx --from git+https://github.com/joaocarmo/mtg-mcp-server mtg-mcp-server
```

## Docs

- [Cookbook](docs/COOKBOOK.md): example prompts with real output
- [Tools](docs/TOOL_DESIGN.md): every tool, prompt and resource
- [Architecture](docs/ARCHITECTURE.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

## Data sources

[Scryfall](https://scryfall.com), [Commander Spellbook](https://commanderspellbook.com), [17Lands](https://www.17lands.com), [EDHREC](https://edhrec.com), [Moxfield](https://www.moxfield.com), [MTGGoldfish](https://www.mtggoldfish.com) and [TopDeck.gg](https://topdeck.gg). Licences and usage terms: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Disclaimer

mtg-mcp-server is unofficial Fan Content permitted under the [Fan Content Policy](https://company.wizards.com/en/legal/fancontentpolicy). Not approved/endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC.

## License

MIT, see [LICENSE](LICENSE).
