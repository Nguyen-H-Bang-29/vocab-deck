"""
Shared application state and constants.

All runtime singletons are declared here and populated by app.py on startup.
Route modules import from here — never from app.py — to avoid circular imports.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent
DATA_ROOT = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_ROOT / "raw"
PROCESSED_DATA_DIR = DATA_ROOT / "processed"
# Allow the runtime dir (DB + logs) to be redirected to a persistent volume
# without moving the read-only processed data. Defaults to the local layout.
RUNTIME_DATA_DIR = Path(os.environ.get("VOCAB_DECK_RUNTIME_DIR", str(DATA_ROOT / "runtime")))
LOG_DIR = RUNTIME_DATA_DIR / "logs"

for _d in [RAW_DATA_DIR, PROCESSED_DATA_DIR, RUNTIME_DATA_DIR, LOG_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("vocab_deck.server")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    _h = RotatingFileHandler(
        LOG_DIR / "server_errors.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    _h.setLevel(logging.ERROR)
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(_h)

SOURCE_KEY: str = os.environ.get("VOCAB_DECK_SOURCE", "vocab").strip().lower() or "vocab"
ENRICHED_FILE = PROCESSED_DATA_DIR / (
    "vocab_enriched.json" if SOURCE_KEY == "vocab" else f"{SOURCE_KEY}_enriched.json"
)
DB_FILE = RUNTIME_DATA_DIR / "vocab_deck.db"

APP_CONFIG: dict[str, int | float] = {
    "practicing_limit": 120,
    "min_attempts_proficient": 4,
    "min_attempts_master": 8,
    "proficient_accuracy_threshold": 80.0,
    "master_accuracy_threshold": 92.0,
    "daily_questions": 10,
    "personalization_pool_limit": 180,
    "incorrect_carousel_size": 8,
    "incorrect_window_attempts": 120,
    "carousel_synonyms_limit": 4,
    "carousel_antonyms_limit": 4,
    "lecture_words": 6,
}

# Runtime singletons — set by app.py after initialization
vocab_data: list[dict[str, Any]] = []
challenge_gen = None   # VocabChallenge | None
thesaurus = None       # ThesaurusAPI | None
anthropic_client = None  # anthropic.Anthropic | None
