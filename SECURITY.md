# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it through
[GitHub Security Advisories](https://github.com/joaocarmo/mtg-mcp-server/security/advisories/new).

**Do not open a public issue for security vulnerabilities.**

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response Timeline

- **Acknowledgement**: Within 48 hours of report submission
- **Assessment**: Within 1 week
- **Fix**: Depends on severity; critical issues prioritised

## Scope

### In Scope

- Dependency vulnerabilities (outdated packages with known CVEs)
- Environment variable exposure (e.g., `.env` files committed to version control)
- Input validation issues in tool parameters
- Logging of sensitive data to stderr
- Leaks of the TopDeck.gg API key into logs or tool output

### Out of Scope

Vulnerabilities in the upstream services: Scryfall, Commander Spellbook, 17Lands, EDHREC, Moxfield, MTGGoldfish, TopDeck.gg and the Comprehensive Rules download from Wizards of the Coast. Report those to the service.

## Credentials

Every backend except TopDeck.gg is public and needs no credentials. The `topdeck_` tools need a TopDeck.gg API key, which each user supplies in `MTG_MCP_TOPDECK_API_KEY`. The server holds it as a pydantic `SecretStr` and sends it only in the `Authorization` header of requests to the TopDeck.gg API. It never logs the key.

## Dependency Auditing

This project uses `pip-audit` to check for known vulnerabilities in dependencies.
Run it locally (it is a dev dependency, installed by `mise run setup`):

```bash
uv run pip-audit
```
