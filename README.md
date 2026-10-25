# Vocab Deck

A GRE/GregMat vocabulary trainer with daily exercises, progress tracking, streaks, and level-based personalization.

## Current Stack

- Python: 3.14+
- Package manager: uv
- Backend: Flask 3.x + flask-cors 4.x
- PDF parsing: pypdf 6.x
- API client: requests 2.31+
- Test framework: pytest 8+
- Database: SQLite
- External data source: Merriam-Webster Collegiate Thesaurus API

## Version & Functionality Changes

### v0.6.0 (Current)
- Added homepage dashboard endpoint: `GET /api/dashboard/<username>`
- Added homepage sections for:
  - latest exercises
  - result summary (today + all-time)
  - trend history (last 14 days)
  - current/best streaks
- Replaced chart-based mastery display with a level dictionary table (all words shown)
- Added table-level filtering and pagination in homepage UI
- Fixed table header visual/alignment behavior (opaque sticky header + fixed columns)
- Added settings popup/menu for runtime configuration of leveling/personalization parameters
- Added clickable Merriam-Webster word links across frontend word displays
- Added homepage carousel for recent incorrect words with definitions and synonym/antonym review cards
- Added projected progress panel in settings (ETA to 50/75/90% proficient and master)
- Added level dictionary (`level_dict`) with per-word metadata:
  - occurrences
  - correct
  - accuracy
  - level (`not-learned`, `practicing`, `proficient`, `master`)
  - level color
- Personalized exercise generation now uses level dictionary from history only (no visible mastery score)
- Enforced controlled dictionary progression via practicing-cap policy (`X = 120` by default)
- Added endpoint tests for the new dashboard route

### v0.5.0
- Fixed production 500 issue for `/api/daily-challenge` when API key is missing
- Made `VocabChallenge` support `thesaurus=None` for runtime challenge generation
- Added regression tests proving challenge endpoints work with no API key

### v0.4.0
- Added Flask web app (`app.py`) and frontend homepage (`static/index.html`)
- Added challenge/validation/progress API routes
- Added SQLite persistence (`user_progress`, `challenge_history`)

### v0.3.0
- Added Merriam-Webster API integration (`thesaurus.py`)
- Added enrichment and matching logic (`quiz.py`)
- Added API-oriented helper functions for synonym/antonym lookup and relation match

### v0.2.0
- Improved vocabulary extraction pipeline
- Exported word data to JSON and CSV outputs

### v0.1.0
- Initial project scaffold and PDF extraction baseline

## Quick Start

1. Install dependencies:

```bash
uv sync
```

2. Optional API key (only required for enrichment/re-enrichment):

```powershell
$env:MERRIAM_WEBSTER_API_KEY = "your-api-key-here"
```

3. Run warm-up (extract + enrich) for a source:

```bash
uv run start.py --mode warmup --source vocab
```

For other sources (e.g., GRE quant):

```bash
uv run start.py --mode warmup --source gre_quant
```

Place source PDFs under `data/raw/` (for example `data/raw/GregMat Vocab.pdf`).

4. Start web app (separate from warm-up):

```bash
uv run start.py --mode web --source vocab
```

Or run both in one command:

```bash
uv run start.py --mode all --source vocab
```

5. Open:

- http://localhost:5000

## Runtime Behavior (Important)

- Warm-up and web are decoupled:
  - Warm-up: `read_vocab.py` / `start.py --mode warmup`
  - Web app: `app.py` / `start.py --mode web`
- Web app loads source data based on `VOCAB_DECK_SOURCE` (set automatically by `start.py --source ...`).
- Data file used by web app:
  - `vocab` -> `data/processed/vocab_enriched.json`
  - any other source -> `data/processed/<source>_enriched.json` (e.g. `data/processed/gre_quant_enriched.json`)
- You do **not** need to set the API key to run the challenge homepage if enriched data already exists.
- API key is needed when generating or refreshing enrichment data from Merriam-Webster.

## Input Sources (Warm-up)

Warm-up inputs are configured in `data_sources.py`.

Current built-in sources:
- `vocab` (default): GregMat vocabulary PDF parsing profile
- `gre_quant`: GRE quant PDF parsing profile

You can add new sources by registering a new `SourceSpec` in `data_sources.py` with:
- `default_pdf`
- `line_regex`
- `skip_prefixes`

This keeps extraction rules source-specific while the web app remains unchanged.

## Leveling & Personalization Algorithm (Source of Truth)

This section is the canonical reference for behavior changes.

### 1) Level assignment (history-only)
For each user and word, compute from `challenge_history`:
- `attempts` = total times word has appeared
- `correct` = total correct answers
- `accuracy = correct / attempts * 100` (0 when `attempts = 0`)

Levels are assigned strictly by attempts + accuracy:
- `not-learned`: `attempts == 0`
- `practicing`: attempted but not yet at proficient/master thresholds
- `proficient`: `attempts >= 4` and `accuracy >= 80%`
- `master`: `attempts >= 8` and `accuracy >= 92%`

### 1b) SRS override (explicit mastery)
- A word rated `quality = 5` ("Easy") in `POST /api/srs/rate` is treated as already known by the user.
- `build_level_dictionary` forces that word's `level` to `master` regardless of what `challenge_history` shows, and flags it `srs_mastered: true`.
- This is a one-way signal: there's no automatic "un-mastering" — the word simply stops being selected (see §2), so it never resurfaces to be re-rated.

### 2) Controlled progression (practicing cap)
- Let `X` be the maximum number of active practicing words (`PRACTICING_WORD_LIMIT`, default `120`).
- Words flagged `srs_mastered` (§1b) are excluded entirely before pool construction — not just deprioritized to reinforcement.
- Daily personalization pool is built in this order:
  1. all current `practicing` words
  2. then new `not-learned` words only if practicing count is below `X` (fill the remaining slots)
  3. then `proficient/master` words (excluding `srs_mastered`) as reinforcement fallback
- This guarantees slow movement across the dictionary and prevents introducing more new words once active practicing reaches `X`.

### 3) API payload contract
- `GET /api/dashboard/<username>` returns:
  - `level_dict` (all words, including `srs_mastered: bool` per §1b)
  - `word_coverage.words` (all words with level metadata)
  - `word_coverage.level_counts`
  - `level_policy` (includes practicing limit and level taxonomy)

### 4) Future modification rule
- If leveling/personalization behavior changes, update this README section first, then code/tests.
- Treat this section as source of truth for future agents and maintainers.

### 5) Configurable parameters (UI + API)
Runtime settings are adjustable from frontend settings popup and API:
- `practicing_limit` (X)
- `daily_questions`
- `min_attempts_proficient`
- `min_attempts_master`
- `proficient_accuracy_threshold`
- `master_accuracy_threshold`
- `personalization_pool_limit`
- `incorrect_carousel_size`
- `incorrect_window_attempts`
- `carousel_synonyms_limit`
- `carousel_antonyms_limit`

Validation rules:
- `min_attempts_master >= min_attempts_proficient`
- `master_accuracy_threshold >= proficient_accuracy_threshold`

## Core API Routes

- `GET /api/status`
- `GET /api/settings`
- `POST /api/settings`
- `GET /api/projection/<username>`
- `GET /api/incorrect-carousel/<username>`
- `GET /api/daily-challenge?username=<name>`
- `GET /api/challenge/synonym?difficulty=<easy|medium|hard>`
- `GET /api/challenge/antonym?difficulty=<easy|medium|hard>`
- `POST /api/validate`
- `POST /api/update-progress`
- `GET /api/progress/<username>`
- `GET /api/dashboard/<username>`
- `GET /api/random-word`
- `GET /api/word/<word>`

## Tests

```bash
uv run pytest -v tests/test_endpoints.py
```

## Main Files

Top-level keeps entry points only (`app.py`, `start.py`, `main.py`, helper scripts).

- `app.py`: Flask API + analytics endpoints
- `src/vocab_deck/quiz.py`: challenge generation and answer validation
- `src/vocab_deck/thesaurus.py`: Merriam-Webster client and cache
- `src/vocab_deck/read_vocab.py`: source-driven warm-up extraction/enrichment pipeline
- `src/vocab_deck/data_sources.py`: warm-up source registry (`vocab`, `gre_quant`, ...)
- `start.py`: launcher with `web|warmup|all` modes
- `static/index.html`: dashboard/home page
- `static/practice.html`: lecture + practice page
- `static/styles/index.css`: homepage styles
- `static/styles/practice.css`: practice page styles
- `data/raw/`: source PDFs
- `data/processed/`: extracted/enriched JSON/CSV outputs
- `data/runtime/`: SQLite DB + runtime logs
- `tests/test_endpoints.py`: API regression tests
