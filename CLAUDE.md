# CLAUDE.md — vocab-deck

GRE/GregMat vocabulary trainer with daily exercises, spaced repetition, progress tracking, streaks, and level-based personalization. Current version: **v0.6.0**.

## Tech Stack

- Python 3.14+ (`uv` as package manager, see `.python-version`)
- Flask 3.x + flask-cors; SQLite for persistence
- pypdf 6.x for PDF extraction; requests 2.31+ for Merriam-Webster API
- anthropic 0.25+ for Claude-powered reading passage generation
- python-dotenv for `.env` loading
- pytest 9+ for tests; playwright 1.40+ for UI/E2E tests
- Frontend: vanilla HTML/CSS/JS (no framework)

## Project Layout

```
app.py                          Flask entry point — wires singletons, registers blueprints
start.py                        Launcher: --mode web|warmup|all --source vocab
state.py                        Shared runtime singletons (DB_FILE, vocab_data, APP_CONFIG, …)
database.py                     DB init (init_db) + low-level write helpers
services.py                     Business logic: leveling, SM-2, session management, carousel

routes/
    pages.py                    Serves index.html (/), practice.html (/practice)
    settings.py                 /api/status, /api/settings, /api/profiles, /api/random-word, /api/word/<word>
    challenge.py                /api/lecture/<username>, /api/daily-challenge, /api/challenge/<type>,
                                /api/validate, /api/practice-session/*, /api/incorrect-carousel/*
    progress.py                 /api/projection/<username>, /api/progress/<username>, /api/dashboard/<username>,
                                /api/update-progress
    srs.py                      /api/srs/rate  (SM-2 confidence ratings)
    passage.py                  /api/reading-passage  (Claude-generated contextual passages)

vocab_deck/
    quiz.py                     VocabChallenge: challenge generation + answer validation
    thesaurus.py                Merriam-Webster client with in-memory cache
    read_vocab.py               Source-driven warm-up: PDF extraction + enrichment
    data_sources.py             Source registry (SourceSpec per PDF profile)

static/
    index.html                  Dashboard/home page
    practice.html               Lecture + practice quiz page
    js/index.js
    js/practice.js
    styles/index.css
    styles/practice.css

data/raw/                       Source PDFs (e.g. "GregMat Vocab.pdf")
data/processed/                 vocab_enriched.json, vocab_words.json, *.csv
data/runtime/                   SQLite DB (vocab_deck.db) + rotating logs

tests/
    test_endpoints.py           API regression tests (pytest, stubs state/database)
    test_ui.py                  Playwright UI/E2E tests (requires running server on :5000)

scripts/
    inspect_pdf.py              Dev helper: inspect a raw PDF's text content
    test_api.py                 Dev helper: manual API smoke tests
```

## Environment

```bash
uv sync
cp .env.example .env           # then fill in keys
export MERRIAM_WEBSTER_API_KEY="your-key"   # only needed for (re-)enrichment
export ANTHROPIC_API_KEY="your-key"         # only needed for reading passage generation
```

## Running

```bash
uv run start.py --mode warmup --source vocab   # extract + enrich PDF
uv run start.py --mode web --source vocab      # start Flask on :5000
uv run start.py --mode all --source vocab      # both

uv run pytest -v tests/test_endpoints.py
uv run pytest -v tests/test_ui.py              # requires server running on :5000
```

Warm-up and web are decoupled. The web app reads `data/processed/<source>_enriched.json` (set via `VOCAB_DECK_SOURCE` env var, wired automatically by `start.py --source`). No API key needed once enriched data exists.

## Core API Routes

```
GET  /api/status
GET  /api/settings
POST /api/settings
GET  /api/profiles
GET  /api/random-word
GET  /api/word/<word>

GET  /api/projection/<username>
GET  /api/incorrect-carousel/<username>
GET  /api/lecture/<username>
GET  /api/daily-challenge?username=<name>&num_questions=<n>&prefer=<word,…>
GET  /api/challenge/<synonym|antonym>?difficulty=easy|medium|hard&username=<name>
POST /api/validate
POST /api/update-progress
GET  /api/progress/<username>
GET  /api/dashboard/<username>
GET  /api/practice-session/<username>?new=1
POST /api/practice-session/<session_id>/answer

POST /api/srs/rate               { username, word, quality }  quality ∈ {1..5}
POST /api/reading-passage        { words: [...] }
```

## Key Patterns

### Shared state (`state.py`)

All runtime singletons live in `state.py`. Route modules import `import state as ext` and access `ext.vocab_data`, `ext.DB_FILE`, `ext.APP_CONFIG`, etc. Never import from `app.py` in route/service code — that creates circular imports.

### ThesaurusAPI

In-memory cache per instance. Reuse the same instance to stay within the free tier (1,000 req/day). "Word not found" returns empty lists — handled gracefully.

```python
from vocab_deck.thesaurus import ThesaurusAPI, load_api_key
api = ThesaurusAPI(load_api_key())
synonyms = api.get_synonyms("happy", limit=10)
```

### Quiz / VocabChallenge

`VocabChallenge` generates Duolingo-style questions from enriched data. Supports `thesaurus=None` (no API key needed if data is already enriched). Difficulty maps to number of choices: easy=3, medium=4, hard=5.

### SM-2 SRS (`services.sm2_next`)

Implements the SM-2 algorithm (Wozniak 1987). Called by `POST /api/srs/rate`; stores state per (username, word) in `srs_ratings`. Quality scale: 1=blackout, 3=hard, 4=good, 5=easy. A `quality=5` ("Easy") rating forces the word's level to `master` in `build_level_dictionary` and excludes it outright from `personalization_pool` — see README "Leveling & Personalization Algorithm" §1b.

### Reading passages (`routes/passage.py`)

Uses Claude (claude-haiku-4-5) to generate a ~120-word GRE-level paragraph that contextualises the session's vocabulary words. Results are cached in `reading_passages` by a sorted word-set key, so the same word set never hits the API twice.

### API response shape

All quiz helper functions return dicts with a `status` field:
```python
{"status": "success", "synonyms": [...]}
{"is_match": True}
```

### Test isolation

Tests patch `state` and `database` directly, not `app`:
```python
import state as ext, database
monkeypatch.setattr(ext, "DB_FILE", tmp_path / "test.db")
monkeypatch.setattr(ext, "vocab_data", SAMPLE_VOCAB)
monkeypatch.setattr(ext, "challenge_gen", StubChallengeGen())
monkeypatch.setattr(ext, "APP_CONFIG", dict(BASE_CONFIG))
database.init_db()
```

### Adding a new vocab source

Register a `SourceSpec` in `vocab_deck/data_sources.py` with `default_pdf`, `line_regex`, and `skip_prefixes`. No changes to `app.py` or `quiz.py` needed.

## Leveling & Personalization Algorithm (Source of Truth)

**The canonical spec lives in `README.md` under "Leveling & Personalization Algorithm".** Before changing behavior in `services.py`, `routes/challenge.py`, or any frontend logic, update that README section first.

Summary:
- Levels assigned from `challenge_history` only: `not-learned` → `practicing` → `proficient` (≥4 attempts, ≥80% accuracy) → `master` (≥8 attempts, ≥92% accuracy).
- Daily pool: all `practicing` words first, then `not-learned` fill up to `PRACTICING_WORD_LIMIT` (default 120), then `proficient/master` as reinforcement.
- All thresholds are runtime-configurable via `POST /api/settings` and the frontend settings popup.

## Database Schema

Six tables in `data/runtime/vocab_deck.db`:

| Table | Purpose |
|---|---|
| `user_progress` | Daily score, total questions, streak per (username, date) |
| `challenge_history` | Per-attempt record: word, type, answer, correctness |
| `lecture_history` | Words shown in lecture cards |
| `challenge_sessions` | Resumable practice sessions with serialized Q&A |
| `srs_ratings` | SM-2 state per (username, word): interval, reps, EF, next review |
| `reading_passages` | Cached Claude-generated passages keyed by sorted word set |

## Coding Conventions

- Strict typing throughout — Pyright strict baseline. Full annotations on every function.
- `list[str]`, `dict[str, int]`, `X | None` (PEP 604). No bare `Any` without justification.
- Tests in `tests/`. Fixtures typed. New non-trivial modules get a companion test file.
- Ruff for lint/format; no `print()` in non-script code (use `logging`).
- Immutable data patterns preferred; no silent mutation of dicts passed as arguments.
