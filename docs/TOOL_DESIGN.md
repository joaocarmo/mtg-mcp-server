# MTG MCP Server — Tool Catalog

Every tool, prompt and resource the server exposes. Namespaced tools come from mounted backends; unprefixed tools are workflow tools on the orchestrator.

**Conventions (apply to every tool):**
- Annotations: `readOnly=true, idempotent=true, openWorld=true`.
- Every tool returns markdown (`content`) plus a structured `data` dict (`structured_content`).
- `fmt` below means `response_format: "detailed" | "concise" = "detailed"`. All workflow tools accept it.
- `limit: 0` means "all" where noted.
- The orchestrator also exposes `ping` (health check; returns plain text "pong", no structured data), which brings the total to 61 tools.

---

## Scryfall (`scryfall_`)

| Tool | Inputs | Output | Backend |
|------|--------|--------|---------|
| `scryfall_search_cards` | `query` (Scryfall syntax, e.g. `f:commander id:sultai t:creature cmc<=3`), `page=1`, `limit=30` (0=all), `fmt` | Matching cards (name, type, mana, price) + pagination; slim card fields | `search_cards()` |
| `scryfall_card_details` | `name`, `fuzzy=false` | Full card: mana, type, oracle text, colors, identity, legalities (legal, banned, restricted), prices (USD, USD foil, EUR), set, rarity, EDHREC rank | `get_card_by_name()` |
| `scryfall_card_rulings` | `name` | Rulings with dates and sources | `get_card_by_name()` → `get_rulings()` |
| `scryfall_set_info` | `set_code` (e.g. "dom") | Name, code, release date, type, card count, icon URI | `get_set()` |

## Commander Spellbook (`spellbook_`)

| Tool | Inputs | Output | Backend |
|------|--------|--------|---------|
| `spellbook_find_combos` | `card_name`, `color_identity=None` ("sultai", "BUG", "wubrg"), `limit=10` | Combos: cards, prerequisites, steps, results | `find_combos()` |
| `spellbook_combo_details` | `combo_id` (e.g. "2120-5329") | Cards, zone requirements, steps, results | `get_combo()` |
| `spellbook_find_decklist_combos` | `commanders: list`, `decklist: list` | Included and almost-included combos | `find_decklist_combos()` |
| `spellbook_estimate_bracket` | `commanders: list`, `decklist: list` | Bracket tag, banned cards, game changers, two-card combos, lock combos | `estimate_bracket()` |

## 17Lands (`draft_`)

| Tool | Inputs | Output | Backend |
|------|--------|--------|---------|
| `draft_card_ratings` | `set_code` ("LCI"), `event_type="PremierDraft"`, `limit=50` (0=all), `sort_by="gih_wr"` (also `alsa`, `iwd`, `name`), `fmt` | Per card: color, rarity, GIH WR, ALSA, IWD, games; slim rating fields | `card_ratings()` |
| `draft_archetype_stats` | `set_code`, `start_date`, `end_date` (YYYY-MM-DD, **required**), `event_type="PremierDraft"` | Win rate and games per color combination, incl. mono-colour and summary rows | `color_ratings()` |

## EDHREC (`edhrec_`)

| Tool | Inputs | Output | Backend |
|------|--------|--------|---------|
| `edhrec_commander_staples` | `commander_name`, `category=None` ("creatures", "lands", …), `limit=10` per category (0=all), `fmt` | Top cards with synergy, inclusion %, decks analyzed; slim EDHREC fields | `commander_top_cards()` |
| `edhrec_card_synergy` | `card_name`, `commander_name` | Synergy, inclusion %, deck count, signature-card flag | `card_synergy()` |

## Moxfield (`moxfield_`, tag: beta)

| Tool | Inputs | Output | Backend |
|------|--------|--------|---------|
| `moxfield_decklist` | `deck_id` (ID or full URL) | Author, description, dates, URL, then decklist by board (commanders, main, side, companions); structured metadata + per-board lists | `get_deck()` |
| `moxfield_search_decks` | `query=None`, `format=None`, `sort="Updated"` (also "Created", "Views"), `page=1`, `page_size=20` | Paginated summaries: name, format, author, colors, counts, URL | `search_decks()` |
| `moxfield_user_decks` | `username`, `format=None` | User's public decks; verifies the user exists first | `search_users()` + `search_decks()` |

## MTGGoldfish (`goldfish_`, tag: beta)

| Tool | Inputs | Output | Backend |
|------|--------|--------|---------|
| `goldfish_metagame` | `format`, `fmt` | Archetypes: rank, name, meta %, decks, paper price | `get_metagame()` |
| `goldfish_archetype_list` | `format`, `archetype` ("Boros Energy"), `fmt` | Deck metadata (author, event, result, date) + main and sideboard | `get_archetype()` |
| `goldfish_format_staples` | `format`, `limit=20`, `fmt` | Rank, name, % of decks, avg copies | `get_format_staples()` |

## Scryfall bulk data (`bulk_`)

Rate-limit-free; backed by `ScryfallBulkClient`.

| Tool | Inputs | Output | Backend |
|------|--------|--------|---------|
| `bulk_card_lookup` | `name` | Full card incl. P/T, keywords, prices (USD, foil, EUR), legalities (legal, banned, restricted), EDHREC rank, images | `get_card()` |
| `bulk_card_search` | `query`, `search_field="name"` (or "type", "text"), `limit=20` | Name, mana, type line | `search_cards()` / `search_by_type()` / `search_by_text()` |
| `bulk_format_legality` | `card_name`, `format` | legal / not_legal / banned / restricted | `get_card()` |
| `bulk_format_search` | `format`, `query`, `limit=20` | Format-legal matches | `filter_cards()` |
| `bulk_format_staples` | `format`, `color=None` (identity), `card_type=None`, `limit=20`, `ranking_mode="auto"` (or `edhrec`, `competitive`), `fmt` | Ranked staples. Auto mode: singleton formats (Commander, Brawl, Oathbreaker) use EDHREC rank; other formats use a mana-efficiency score | `filter_cards()` |
| `bulk_ban_list` | `format` | Banned and restricted cards | `filter_cards()` |
| `bulk_random_card` | `format=None`, `card_type=None` | Random card, full details | `filter_cards()` |
| `bulk_similar_cards` | `card_name`, `limit=10` | Similar by type, keywords or mana cost; shared attributes highlighted | `get_card()` + `filter_cards()` |

---

## Workflow tools (no namespace)

Implemented as pure async functions in `workflows/` and wrapped in `workflows/server.py`. They run backend calls concurrently with `asyncio.gather(return_exceptions=True)`. **Required** backends fail the call (as a `ToolError`, or an explanatory message where noted). **Optional** backends degrade: their data shows as missing/N/A and the gap is noted in the output. "Progress" means the tool reports `ctx.report_progress` steps.

### Commander

| Tool | Inputs | Output | Backends |
|------|--------|--------|----------|
| `commander_overview` | `commander_name` | Card header (mana, type, text, identity, P/T, rarity, EDHREC rank), top 5 combos, top 10 EDHREC staples by inclusion with synergy, Data Sources footer | Scryfall (req), Spellbook, EDHREC |
| `evaluate_upgrade` | `card_name`, `commander_name` | Card details incl. price; synergy (score, inclusion, decks); top 5 combos enabled; Data Sources footer | Scryfall (req), Spellbook, EDHREC |
| `suggest_cuts` | `decklist`, `commander_name`, `num_cuts=5` | Ranked cut candidates with reasoning, source status, failure notes. Score: low synergy + low inclusion = more cuttable; combo pieces protected (−2.0, "PROTECTED"); no data = +0.5 ("Low confidence") | Spellbook (req), EDHREC |
| `card_comparison` | `cards` (2-5), `commander_name` | Table: mana, type, synergy, inclusion, combo count, price. A missing card fails the call; EDHREC/Spellbook failures show N/A. Progress ×3 | Scryfall + Spellbook (req), EDHREC |
| `budget_upgrade` | `commander_name`, `budget` (max USD per card), `num_suggestions=10` | Ranked by synergy per dollar: synergy, inclusion, price, synergy/$. Returns a message if EDHREC is disabled or nothing fits. Progress ×2 | Scryfall + EDHREC (req) |
| `deck_analysis` | `decklist`, `commander_name` | Mana curve, colour pips, combos and bracket, total/avg budget, 5 lowest-synergy cards, unresolved cards, footer. Bulk-first card resolution. Progress ×3 | Bulk/Scryfall (req), Spellbook, EDHREC |
| `commander_comparison` | `commanders` (2-5) | Table: mana, type, identity, EDHREC rank, combo count, top staples, unique strengths. Progress ×3 | Bulk/Scryfall + Spellbook (req), EDHREC |
| `tribal_staples` | `tribe` ("Elf"), `color_identity=None`, `format=None` | Lords, synergy pieces, members, support, each with oracle text and price | Bulk (req), EDHREC |
| `precon_upgrade` | `decklist`, `commander`, `budget=50.0`, `num_upgrades=10` | Swap pairs (cut → add) with reasoning, ranked by synergy delta; source status | Bulk/Scryfall + Spellbook (req), EDHREC |
| `color_identity_staples` | `color_identity` ("simic", "UG"), `category=None` | Staples by EDHREC rank with prices; falls back to the bulk-data EDHREC rank when EDHREC is off | Bulk (req), EDHREC |

### Draft / Limited

| Tool | Inputs | Output | Backends |
|------|--------|--------|----------|
| `draft_pack_pick` | `pack`, `set_code`, `current_picks=None` | Table ranked by GIH WR with color, rarity, ALSA, IWD, games; `[on-color]`/`[off-color]` when picks are given; "No data" section | 17Lands (req; it already has name, colour and rarity, so no Scryfall) |
| `set_overview` | `set_code`, `event_type="PremierDraft"` | Median GIH WR, top 10 commons and uncommons, trap rares/mythics (below median). Progress ×2 | 17Lands (req) |
| `sealed_pool_build` | `pool` (84-90 names), `set_code` | Top 1-3 two-colour 40-card builds: list by type, curve, removal/bomb counts. Scored by GIH WR, with a heuristic fallback (rarity, bomb/removal detection). Progress ×3 | Bulk (req), 17Lands |
| `draft_signal_read` | `picks` (in order), `set_code`, `current_pack=None` | Colour commitment, ALSA openness per colour, recommended direction, optional pack ranking | Bulk + 17Lands (req) |
| `draft_log_review` | `picks` (P1P1…P3P14), `set_code`, `final_deck=None` | Per pick: GIH WR and verdict; average; grade A (≥60%) … F (<50%); optional deck inclusion analysis | Bulk + 17Lands (req) |

### Deck building and cross-format

| Tool | Inputs | Output | Backends |
|------|--------|--------|----------|
| `theme_search` | `theme` ("sacrifice", "tokens"), `color_identity=None`, `format=None`, `max_price=None`, `limit=20` | Cards matched by oracle-text patterns, sorted by match quality, with type, text excerpt, price | Bulk (req) |
| `build_around` | `cards` (1-5), `format` (req), `budget=None`, `limit=20` | Resolved cards, detected mechanics, synergy candidates, combo potential | Bulk + Spellbook (req) |
| `complete_deck` | `decklist`, `format`, `commander=None`, `budget=None` | Current composition, target size, category gaps (creatures, removal, draw, …) with suggestions; notes when suggestions are unavailable | Bulk/Scryfall (req); suggestions need bulk |
| `deck_validate` | `decklist`, `format`, `commander=None`, `sideboard=None` | VALID/INVALID plus legality, size, copy limits, colour identity (Commander), rarity (Pauper) | Bulk (req) |
| `suggest_mana_base` | `decklist`, `format`, `total_lands=None` | Pip analysis, land count, basic split, format-legal duals | Bulk (req) |
| `price_comparison` | `cards` | USD, USD foil, EUR per card + total | Bulk (req) |
| `rotation_check` | `cards=None` | Standard-legal sets by release date, rotation timing, optional per-card status | Scryfall (sets) + Bulk |

### Constructed: metagame and sideboard

Archetype and matchup names are fuzzy-matched.

| Tool | Inputs | Output | Backends |
|------|--------|--------|----------|
| `metagame_snapshot` | `format` | Archetypes tiered T1 >10%, T2 3-10%, T3 <3%, with share, decks, price. Returns an error message if MTGGoldfish is unavailable | MTGGoldfish |
| `archetype_decklist` | `format`, `archetype` | Metadata, main and sideboard, card roles, optional pricing | MTGGoldfish (req), Bulk |
| `archetype_comparison` | `format`, `archetypes` (2-4) | Share, decks, price, colours, main/side sizes; shared staples | MTGGoldfish (req), Bulk |
| `format_entry_guide` | `format`, `budget=None` | Format rules, archetypes by budget, recommended first deck, cross-archetype staples; returns the rules even with no metagame data | MTGGoldfish, Bulk (all optional) |
| `suggest_sideboard` | `decklist`, `format`, `meta_context=None` | 15 cards by category (graveyard hate, removal, counters, wipes, …) within the deck's colour identity, format staples marked; categories with no on-colour answer listed in `empty_categories` | Bulk (req), MTGGoldfish |
| `sideboard_guide` | `decklist`, `sideboard`, `format`, `matchup` | Matchup strategy, IN/OUT plan with per-card reasoning, balanced swaps. Colour hosers follow the matchup's colours (MTGGoldfish, else the matchup name) | Bulk (req), MTGGoldfish |
| `sideboard_matrix` | `sideboard`, `format`, `matchups=None` (auto from metagame) | Rows = sideboard cards, columns = matchups, cells IN/OUT/FLEX. Colour hosers follow each matchup's colours (MTGGoldfish, else the matchup name) | Bulk (req), MTGGoldfish |

### Rules engine

Backed by the local `RulesService`; bulk data, when enabled, supplies card examples and lookups.

| Tool | Inputs | Output |
|------|--------|--------|
| `rules_lookup` | `query` (rule number like "704.5k", or keyword), `section=None` | Matching rules with parent/child rules and cross-references |
| `keyword_explain` | `keyword` | Glossary definition, related rules, example cards |
| `rules_interaction` | `mechanic_a`, `mechanic_b` | Rules for each, interaction analysis, citations |
| `rules_scenario` | `scenario` (free text) | Extracted concepts with the relevant rules, as a framework for LLM reasoning |
| `combat_calculator` | `attackers`, `blockers`, `keywords=None` | Step-by-step combat phases, card data, combat rules, keyword interactions |

---

## Prompts (18, workflow server)

Each prompt returns step-by-step instructions that chain the tools listed.

| Prompt | Inputs | Steps |
|--------|--------|-------|
| `evaluate_commander_swap` | `commander`, `adding`, `cutting` | card lookups → `card_comparison` → `spellbook_find_combos` → SWAP/KEEP/CONSIDER |
| `deck_health_check` | `commander` | `deck_analysis` → `suggest_cuts` → prioritised recommendations |
| `draft_strategy` | `set_code` | `set_overview` → top archetypes with key commons/uncommons → heuristics cheat sheet (GIH WR/IWD/ALSA thresholds) |
| `find_upgrades` | `commander`, `budget` | `budget_upgrade` → `evaluate_upgrade` on top 5 → recommend 3-5 |
| `build_deck` | `concept`, `format`, `budget=None` | format search → staples → curve/colours → `deck_validate` → `suggest_mana_base` |
| `evaluate_collection` | `cards` (comma-separated) | prices → legality → Commander staple potential |
| `format_intro` | `format` | staples → top archetypes → entry budget |
| `card_alternatives` | `card_name`, `format`, `budget` | card analysis → similar cards → prices → ranked alternatives |
| `rules_question` | `question` | rules lookup → keyword explanation → scenario resolution |
| `build_around_deck` | `cards`, `format`, `budget=None` | theme search → `build_around` → `rotation_check` (Standard) → `complete_deck` → `deck_validate` → `suggest_mana_base` |
| `build_tribal_deck` | `tribe`, `format`, `commander=None`, `budget=None` | `tribal_staples` → `build_around` → `suggest_mana_base` → `deck_validate` |
| `build_theme_deck` | `theme`, `format`, `color_identity=None`, `budget=None` | `theme_search` → `build_around` → `complete_deck` → `deck_validate` → `suggest_mana_base` |
| `upgrade_precon` | `commander`, `budget` | `commander_overview` → `deck_analysis` → `suggest_cuts` → `precon_upgrade` → `deck_validate` |
| `draft_review` | `set_code` | `draft_log_review` → `draft_signal_read` |
| `compare_commanders` | `commanders` | `commander_comparison` → combos → staples |
| `rotation_plan` | — | `rotation_check` → `bulk_similar_cards` → `price_comparison` |
| `explore_format` | `format` | `metagame_snapshot` → `archetype_decklist` → `format_entry_guide` |
| `build_constructed_deck` | `concept`, `format`, `budget=None` | `metagame_snapshot` → `archetype_decklist` (if matching) → `suggest_sideboard` → `deck_validate` |

---

## Resources (5 `mtg://` URIs, JSON)

| URI | Source | Returns |
|-----|--------|---------|
| `mtg://rules/{number}` | Rules | Rule text (e.g. "702.2") |
| `mtg://rules/glossary/{term}` | Rules | Glossary definition |
| `mtg://rules/keywords` | Rules | All keywords with rule refs |
| `mtg://rules/sections` | Rules | Section index |
| `mtg://theme/{theme}` | Workflow | Cards matching a theme |
