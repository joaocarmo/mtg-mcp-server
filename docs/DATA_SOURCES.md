# MTG MCP Server — Data Sources

Every data source evaluated, what it provides, and its status. Endpoints, auth, rate limits and flags for implemented sources: [SERVICE_CONTRACTS.md](SERVICE_CONTRACTS.md).

| Source | Provides | Access | Stability | Status |
|--------|----------|--------|-----------|--------|
| Scryfall API | Every printed card: oracle text, types, mana, legalities, prices (USD/EUR/TIX), rulings, sets, images; full search syntax | REST (+ `POST /cards/collection`, up to 75 cards) | Rock solid | Implemented |
| Scryfall bulk data | Oracle Cards file (~30MB): same card shape as the API, including prices, legalities, images, EDHREC rank | File download | Rock solid | Implemented (replaced MTGJSON, which lacked prices, legalities and images) |
| Commander Spellbook | Every known Commander combo (cards, prerequisites, steps, results); bracket estimation; decklist combo detection. Powers EDHREC's combo feature | REST | Solid, open source | Implemented |
| 17Lands | Arena draft/sealed analytics: GIH WR, OH WR, IWD, ALSA/ATA, archetype win rates. Also bulk CSV datasets per game and per draft at `/public_datasets` (unused) | Undocumented REST | Stable but unofficial | Implemented |
| EDHREC | Commander metagame: top cards per commander with synergy and inclusion, average decks, themes, salt scores | Reverse-engineered JSON (`pyedhrec` is the best reference) | Fragile | Implemented, flagged |
| Comprehensive Rules | Full rules text, glossary, keyword rules | Wizards-hosted text file | Stable | Implemented |
| Moxfield | Public decklists, deck/user search. Collection data needs auth (unused) | Reverse-engineered REST | Fragile | Implemented, flagged |
| Spicerack | Paper tournament results: standings, Swiss/bracket records, Moxfield decklist URLs (Modern, Legacy, Pauper, Pioneer, Standard, Premodern, Commander, …) | Documented REST | Solid | Implemented |
| MTGGoldfish | Constructed metagame shares, sample decklists, format staples, deck prices | HTML scraping (no API) | Fragile | Implemented, flagged |
| Archidekt | Public decks with categories and stats | Undocumented REST. Archidekt tolerates reverse-engineering but may lock it down if abused | Fragile | Deferred: EDHREC already aggregates Archidekt (and Moxfield) data |

Existing MCP servers at evaluation time were basic Scryfall wrappers (pato/mtg-mcp, artillect/mtg-mcp-servers, ericraio/mtg-mcp); none covered Spellbook. Every client here is built in-house on httpx.

**Constraints that shape usage:**
- Scryfall's ToS forbids paywalling its data or simply repackaging it.
- 17Lands win rates need 500+ games, and its baseline WR is ~56% because its users skew skilled.
- EDHREC and MTGGoldfish can change without notice, which is why they sit behind feature flags.
