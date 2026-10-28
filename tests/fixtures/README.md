# Test Fixtures

Captured JSON responses from real API calls, used by tests via `respx` mocking. Tests never hit live APIs.

## Capture Process

1. Make a real API call to the target endpoint
2. Save the full JSON response to the appropriate directory
3. Reference in tests via `respx` route mocking with `httpx.Response(200, json=fixture_data)`

## Fixture Files

### `scryfall/`

| File | Source Endpoint | Description |
|------|-----------------|-------------|
| `card_muldrotha.json` | `GET /cards/named?exact=Muldrotha, the Gravetide` | Full card object for Muldrotha |
| `card_sol_ring.json` | `GET /cards/named?exact=Sol Ring` | Full card object for Sol Ring |
| `card_not_found.json` | `GET /cards/named?exact=Nonexistent` | 404 error response |
| `search_sultai_commander.json` | `GET /cards/search?q=commander:sultai+type:creature` | Search result with pagination |
| `rulings_muldrotha.json` | `GET /cards/{id}/rulings` | Rulings for Muldrotha |
| `rulings_sol_ring.json` | `GET /cards/{id}/rulings` | Rulings for Sol Ring |

### `spellbook/`

| File | Source Endpoint | Description |
|------|-----------------|-------------|
| `combos_muldrotha.json` | `GET /variants/?q=card:"Muldrotha"` | Combo search results |
| `combos_not_found.json` | `GET /variants/?q=card:"Nonexistent"` | Empty combo search |
| `combo_detail.json` | `GET /variants/{id}/` | Single combo detail |
| `find_my_combos_response.json` | `POST /find-my-combos` | Decklist combo analysis |
| `estimate_bracket_response.json` | `POST /estimate-bracket` | Bracket estimation result |

### `seventeen_lands/`

| File | Source Endpoint | Description |
|------|-----------------|-------------|
| `card_ratings_lci.json` | `GET /card_ratings/data?expansion=LCI` | Card ratings for Lost Caverns of Ixalan |
| `color_ratings_lci.json` | `GET /color_ratings/data?expansion=LCI` | Color pair archetype stats |

### `edhrec/`

| File | Source Endpoint | Description |
|------|-----------------|-------------|
| `commander_muldrotha.json` | `GET /pages/commanders/muldrotha-the-gravetide.json` | Commander page data |
| `card_spore_frog.json` | `GET /pages/cards/spore-frog.json` | Card synergy page data |
| `commander_not_found.json` | N/A | 404 response for unknown commander |

### `scryfall_bulk/`

| File | Source Endpoint | Description |
|------|-----------------|-------------|
| `bulk_metadata.json` | `GET /bulk-data/oracle_cards` | Bulk data download metadata |
| `oracle_cards_sample.json` | Subset of Oracle Cards bulk download | 12-entry sample (8 playable cards + 4 adversarial non-playable layouts) in Scryfall format |

### `topdeck/`

Player names and IDs are replaced with `Player N` and `pN`, Discord fields are removed, and the deck import URL is a placeholder. Commander, archetype and card names are unchanged. Standings are trimmed.

| File | Source Endpoint | Description |
|------|-----------------|-------------|
| `bulk_edh.json` | `POST /v2/tournaments` (EDH, `last: 7`, `participantMin: 16`) | 3 events: a 16-player top cut, a 4-player top cut, and a test event dated 2030 |
| `bulk_modern.json` | `POST /v2/tournaments` (Modern, `last: 30`, `participantMin: 16`) | 2 events; the second has archetype labels |
| `tournament.json` | `POST /v2/tournaments` (`TID` mode) | 1 event, first 20 standings |
| `player.json` | `GET /v2/tournaments/{TID}/players/{ID}` | Event winner with record, `decklist` text and `deckObj` |
| `player_not_found.json` | `GET /v2/tournaments/{TID}/players/{unknown}` | 404 response |
