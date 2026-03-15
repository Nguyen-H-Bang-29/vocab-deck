"""
Flask API backend for Vocab Deck web interface.
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import json
import random
from pathlib import Path
from datetime import datetime, date, timezone
import os
import sys
import sqlite3
import logging
from logging.handlers import RotatingFileHandler

SRC_DIR = Path(__file__).parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from vocab_deck.thesaurus import ThesaurusAPI, load_api_key
from vocab_deck.quiz import VocabChallenge

app = Flask(__name__, static_folder='static')
CORS(app)

# Paths
PROJECT_ROOT = Path(__file__).parent
DATA_ROOT = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_ROOT / "raw"
PROCESSED_DATA_DIR = DATA_ROOT / "processed"
RUNTIME_DATA_DIR = DATA_ROOT / "runtime"
LOG_DIR = RUNTIME_DATA_DIR / "logs"

for directory in [RAW_DATA_DIR, PROCESSED_DATA_DIR, RUNTIME_DATA_DIR, LOG_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("vocab_deck.server")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    server_handler = RotatingFileHandler(
        LOG_DIR / "server_errors.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    server_handler.setLevel(logging.ERROR)
    server_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(server_handler)

SOURCE_KEY = os.environ.get("VOCAB_DECK_SOURCE", "vocab").strip().lower() or "vocab"
ENRICHED_FILE = PROCESSED_DATA_DIR / ("vocab_enriched.json" if SOURCE_KEY == "vocab" else f"{SOURCE_KEY}_enriched.json")
DB_FILE = RUNTIME_DATA_DIR / "vocab_deck.db"
APP_CONFIG = {
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
    "lecture_words": 6,      # words shown in pre-practice lecture
}

# Initialize API
api_key = load_api_key()
if not api_key:
    print("WARNING: No API key found. Some features will be limited.")
    thesaurus = None
else:
    thesaurus = ThesaurusAPI(api_key)

# Load enriched vocabulary data
def load_vocab_data():
    """Load enriched vocabulary data."""
    if not ENRICHED_FILE.exists():
        return []
    with open(ENRICHED_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

vocab_data = load_vocab_data()

# Initialize challenge generator.
# thesaurus is optional here — challenge generation works entirely from the
# pre-enriched vocab_enriched.json data (synonyms/antonyms already cached).
# The API key / thesaurus instance is only needed when enriching new words.
challenge_gen = VocabChallenge(vocab_data, thesaurus) if vocab_data else None


# Database initialization
def init_db():
    """Initialize SQLite database for user progress."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # User progress table
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            date TEXT NOT NULL,
            score INTEGER DEFAULT 0,
            total_questions INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(username, date)
        )
    ''')
    
    # Challenge history table
    c.execute('''
        CREATE TABLE IF NOT EXISTS challenge_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            word TEXT NOT NULL,
            challenge_type TEXT NOT NULL,
            user_answer TEXT,
            correct_answer TEXT NOT NULL,
            is_correct BOOLEAN NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Lecture history — tracks which words have been shown in pre-practice lectures
    # to ensure rotation across sessions (no word repeats until all pool words have
    # been lectured once).
    c.execute('''
        CREATE TABLE IF NOT EXISTS lecture_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            word TEXT NOT NULL,
            lectured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS challenge_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            questions_json TEXT NOT NULL,
            answers_json TEXT NOT NULL DEFAULT '[]',
            current_index INTEGER DEFAULT 0,
            total_questions INTEGER NOT NULL,
            is_completed BOOLEAN NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()

init_db()


def classify_level_from_history(accuracy: float, attempts: int) -> dict:
    """Classify a word level from user history only (no mastery score exposed)."""
    if attempts == 0:
        return {"level": "not-learned", "color": "#9e9e9e"}
    if attempts >= APP_CONFIG["min_attempts_master"] and accuracy >= APP_CONFIG["master_accuracy_threshold"]:
        return {"level": "master", "color": "#4caf50"}
    if attempts >= APP_CONFIG["min_attempts_proficient"] and accuracy >= APP_CONFIG["proficient_accuracy_threshold"]:
        return {"level": "proficient", "color": "#2196f3"}
    return {"level": "practicing", "color": "#ff9800"}


def build_level_dictionary(username: str) -> dict:
    """Build per-word level dictionary (all vocab words included)."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        SELECT
            word,
            COUNT(*) as occurrences,
            SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct
        FROM challenge_history
        WHERE username = ?
        GROUP BY word
        ORDER BY occurrences DESC, word ASC
    ''', (username,))
    rows = c.fetchall()
    conn.close()

    attempts_by_word = {word.lower(): (occurrences, correct) for word, occurrences, correct in rows}
    level_dict = {}

    for entry in vocab_data:
        word = entry.get("word", "")
        if not word:
            continue

        occurrences, correct = attempts_by_word.get(word.lower(), (0, 0))
        accuracy = round((correct / occurrences) * 100, 1) if occurrences else 0
        classification = classify_level_from_history(accuracy, occurrences)

        level_dict[word] = {
            "occurrences": occurrences,
            "correct": correct,
            "accuracy": accuracy,
            "level": classification["level"],
            "color": classification["color"],
            "word_type": entry.get("word_type", ""),
        }

    return level_dict


def vocab_lookup_map() -> dict:
    """Build case-insensitive lookup map for vocab metadata."""
    return {item.get("word", "").lower(): item for item in vocab_data if item.get("word")}


def lecture_cards_for_words(words: list[str]) -> list:
    """Build lecture cards for a specific ordered set of words."""
    lookup = vocab_lookup_map()
    cards = []

    for word in words:
        entry = lookup.get((word or "").lower(), {})
        raw_senses = entry.get("senses")
        if raw_senses:
            senses = [
                {
                    "word_type": s.get("word_type", ""),
                    "definition": s.get("definition", ""),
                    "synonyms": (s.get("synonyms") or [])[:APP_CONFIG["carousel_synonyms_limit"]],
                    "antonyms": (s.get("antonyms") or [])[:APP_CONFIG["carousel_antonyms_limit"]],
                }
                for s in raw_senses[:6]
            ]
        else:
            senses = [{
                "word_type": entry.get("word_type", ""),
                "definition": entry.get("definition", "Definition unavailable"),
                "synonyms": (entry.get("synonyms") or [])[:APP_CONFIG["carousel_synonyms_limit"]],
                "antonyms": (entry.get("antonyms") or [])[:APP_CONFIG["carousel_antonyms_limit"]],
            }]

        cards.append({
            "word": word,
            "word_type": entry.get("word_type") or (senses[0]["word_type"] if senses else ""),
            "senses": senses,
        })

    return cards


def unique_words_in_questions(questions: list[dict]) -> list[str]:
    """Return unique question words in first-appearance order."""
    seen = set()
    ordered = []
    for question in questions or []:
        word = (question or {}).get("word", "")
        key = word.lower()
        if word and key not in seen:
            seen.add(key)
            ordered.append(word)
    return ordered


def generate_personalized_questions(username: str, num_questions: int | None = None) -> list[dict]:
    """Generate a personalized question set for a user."""
    level_dict = build_level_dictionary(username)
    preferred_words = personalization_pool(
        level_dict,
        limit=APP_CONFIG["personalization_pool_limit"],
    )
    question_count = num_questions or APP_CONFIG["daily_questions"]
    return challenge_gen.generate_daily_challenge(
        num_questions=question_count,
        preferred_words=preferred_words if preferred_words else None,
    )


def normalize_session_answers(questions: list[dict], answers: list | None) -> list:
    """Pad/truncate stored answers to match question count."""
    normalized = list(answers or [])[:len(questions)]
    if len(normalized) < len(questions):
        normalized.extend([None] * (len(questions) - len(normalized)))
    return normalized


def first_unanswered_index(answers: list) -> int:
    """Return the first unanswered question index, or len(answers) if complete."""
    for idx, answer in enumerate(answers):
        if not answer:
            return idx
    return len(answers)


def serialize_session_payload(session_id: int, username: str, questions: list[dict], answers: list) -> dict:
    """Build the API payload for a challenge session."""
    answers = normalize_session_answers(questions, answers)
    current_index = first_unanswered_index(answers)
    lecture_words = unique_words_in_questions(questions)
    score = sum(1 for answer in answers if answer and answer.get("correct"))
    answered_count = sum(1 for answer in answers if answer)

    return {
        "session_id": session_id,
        "username": username,
        "questions": questions,
        "answers": answers,
        "current_index": current_index,
        "answered_count": answered_count,
        "score": score,
        "is_resumed": answered_count > 0,
        "is_completed": current_index >= len(questions),
        "lecture_words": lecture_words,
        "lecture": lecture_cards_for_words(lecture_words),
    }


def get_active_session_row(username: str):
    """Fetch the latest incomplete session row for a user."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        SELECT id, questions_json, answers_json
        FROM challenge_sessions
        WHERE username = ? AND is_completed = 0
        ORDER BY id DESC
        LIMIT 1
    ''', (username,))
    row = c.fetchone()
    conn.close()
    return row


def get_or_create_practice_session(username: str, force_new: bool = False) -> dict:
    """Return the active incomplete session for a user, or create a new one."""
    row = None if force_new else get_active_session_row(username)
    if row:
        session_id, questions_json, answers_json = row
        questions = json.loads(questions_json)
        answers = json.loads(answers_json or "[]")
        return serialize_session_payload(session_id, username, questions, answers)

    questions = generate_personalized_questions(username)
    answers = [None] * len(questions)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO challenge_sessions (username, questions_json, answers_json, current_index, total_questions, is_completed)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        username,
        json.dumps(questions, ensure_ascii=False),
        json.dumps(answers, ensure_ascii=False),
        0,
        len(questions),
        0,
    ))
    session_id = c.lastrowid
    conn.commit()
    conn.close()

    return serialize_session_payload(session_id, username, questions, answers)


def personalization_pool(level_dict: dict, limit: int = 180) -> list:
    """
    Build a personalized pool while capping active practicing words at X.

    Strategy:
    - Always focus on current practicing words first.
    - Introduce not-learned words only if practicing count is below X.
    - Backfill with proficient/master words when needed for variety.
    """
    if not level_dict:
        return []

    ordered_words = [entry.get("word") for entry in vocab_data if entry.get("word")]

    practicing_words = [
        word for word in ordered_words
        if level_dict.get(word, {}).get("level") == "practicing"
    ]

    not_learned_words = [
        word for word in ordered_words
        if level_dict.get(word, {}).get("level") == "not-learned"
    ]

    reinforcement_words = [
        word for word in ordered_words
        if level_dict.get(word, {}).get("level") in {"proficient", "master"}
    ]

    available_slots = max(0, APP_CONFIG["practicing_limit"] - len(practicing_words))
    intake_words = not_learned_words[:available_slots]

    focus_pool = practicing_words + intake_words
    if len(focus_pool) < limit:
        remaining = limit - len(focus_pool)
        focus_pool.extend(reinforcement_words[:remaining])

    return focus_pool[:limit]


def projected_progress(username: str) -> dict:
    """Estimate days to reach proficiency/mastery milestones based on current settings."""
    level_dict = build_level_dictionary(username)
    total_vocab = len(vocab_data)

    if total_vocab == 0:
        return {
            "username": username,
            "total_vocab": 0,
            "daily_questions": APP_CONFIG["daily_questions"],
            "projections": {"proficient": [], "master": []},
        }

    proficient_now = sum(1 for meta in level_dict.values() if meta["level"] in {"proficient", "master"})
    master_now = sum(1 for meta in level_dict.values() if meta["level"] == "master")

    daily_questions = APP_CONFIG["daily_questions"]
    practicing_limit = APP_CONFIG["practicing_limit"]

    proficiency_velocity = max(0.25, min(daily_questions, practicing_limit) * 0.12)
    master_velocity = max(0.12, min(daily_questions, practicing_limit) * 0.06)

    targets = [50, 75, 90]

    def estimate_days(current_count: int, target_percent: int, velocity: float) -> int:
        target_count = int((target_percent / 100) * total_vocab)
        remaining = max(0, target_count - current_count)
        if remaining == 0:
            return 0
        return int((remaining / velocity) + 0.999)

    proficient_projection = [
        {
            "target_percent": target,
            "target_words": int((target / 100) * total_vocab),
            "current_words": proficient_now,
            "eta_days": estimate_days(proficient_now, target, proficiency_velocity),
        }
        for target in targets
    ]

    master_projection = [
        {
            "target_percent": target,
            "target_words": int((target / 100) * total_vocab),
            "current_words": master_now,
            "eta_days": estimate_days(master_now, target, master_velocity),
        }
        for target in targets
    ]

    return {
        "username": username,
        "total_vocab": total_vocab,
        "daily_questions": daily_questions,
        "projections": {
            "proficient": proficient_projection,
            "master": master_projection,
        },
    }


def build_lecture(username: str) -> list:
    """Legacy lecture builder backed by the active or newly-created practice session."""
    session = get_or_create_practice_session(username)
    return session["lecture"]


def build_incorrect_carousel(username: str) -> list:
    """Build recent incorrect-word cards with definitions and synonym/antonym snippets."""
    if not vocab_data:
        return []

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        SELECT word, timestamp
        FROM challenge_history
        WHERE username = ? AND is_correct = 0
        ORDER BY timestamp DESC
        LIMIT ?
    ''', (username, APP_CONFIG["incorrect_window_attempts"]))
    rows = c.fetchall()
    conn.close()

    lookup = vocab_lookup_map()
    seen = set()
    cards = []

    for word, timestamp_value in rows:
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)

        vocab_entry = lookup.get(key, {})
        raw_senses = vocab_entry.get("senses")

        if raw_senses:
            # Sense-grouped: each definition is paired only with its own syn/ant
            trimmed_senses = [
                {
                    "word_type": sense.get("word_type", ""),
                    "definition": sense.get("definition", ""),
                    "synonyms": (sense.get("synonyms") or [])[:APP_CONFIG["carousel_synonyms_limit"]],
                    "antonyms": (sense.get("antonyms") or [])[:APP_CONFIG["carousel_antonyms_limit"]],
                }
                for sense in raw_senses[:6]  # cap at 6 senses
            ]
        else:
            # Fallback for older enriched data without per-sense grouping
            trimmed_senses = [{
                "word_type": vocab_entry.get("word_type", ""),
                "definition": vocab_entry.get("definition", "Definition unavailable"),
                "synonyms": (vocab_entry.get("synonyms") or [])[:APP_CONFIG["carousel_synonyms_limit"]],
                "antonyms": (vocab_entry.get("antonyms") or [])[:APP_CONFIG["carousel_antonyms_limit"]],
            }]

        cards.append({
            "word": word,
            "timestamp": timestamp_value,
            "word_type": vocab_entry.get("word_type") or (trimmed_senses[0]["word_type"] if trimmed_senses else ""),
            "senses": trimmed_senses,
        })

        if len(cards) >= APP_CONFIG["incorrect_carousel_size"]:
            break

    return cards


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    """Log and return JSON for unhandled server errors."""
    logger.exception("Unhandled API/server exception")

    if request.path.startswith('/api/'):
        return jsonify({"status": "error", "error": "Internal server error"}), 500

    return jsonify({"error": "Internal server error"}), 500
@app.route('/')
def index():
    """Serve the main HTML page."""
    return send_from_directory('static', 'index.html')


@app.route('/practice')
def practice_page():
    """Serve the dedicated practice page."""
    return send_from_directory('static', 'practice.html')

@app.route('/api/status')
def api_status():
    """Check API status and data availability."""
    return jsonify({
        "status": "ok",
        "source": SOURCE_KEY,
        "data_file": ENRICHED_FILE.name,
        "api_key_configured": api_key is not None,
        "vocab_loaded": len(vocab_data) > 0,
        "vocab_count": len(vocab_data),
        "challenge_ready": challenge_gen is not None,
        "config": APP_CONFIG,
    })


@app.route('/api/profiles')
def list_profiles():
    """
    List all known profiles with per-level word counts.

    Returns a list of profile objects:
        { username, level_counts: {not-learned, practicing, proficient, master},
          total_vocab, coverage_pct }
    """
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        SELECT DISTINCT username FROM user_progress
        UNION
        SELECT DISTINCT username FROM challenge_history
        ORDER BY username
    ''')
    usernames = [row[0] for row in c.fetchall()]
    conn.close()

    total_vocab = len(vocab_data)
    profiles = []
    for uname in usernames:
        level_dict = build_level_dictionary(uname)
        counts = {"not-learned": 0, "practicing": 0, "proficient": 0, "master": 0}
        for meta in level_dict.values():
            lvl = meta.get("level", "not-learned")
            counts[lvl] = counts.get(lvl, 0) + 1
        covered = counts["practicing"] + counts["proficient"] + counts["master"]
        coverage_pct = round((covered / total_vocab) * 100, 1) if total_vocab else 0
        profiles.append({
            "username": uname,
            "level_counts": counts,
            "total_vocab": total_vocab,
            "coverage_pct": coverage_pct,
        })

    return jsonify({"profiles": profiles, "total_vocab": total_vocab})


@app.route('/api/settings', methods=['GET'])
def get_settings():
    """Get runtime personalization settings."""
    return jsonify({"settings": APP_CONFIG})


@app.route('/api/settings', methods=['POST'])
def update_settings():
    """Update runtime personalization settings."""
    payload = request.json or {}

    int_fields = {
        "practicing_limit": (1, 1000),
        "min_attempts_proficient": (1, 100),
        "min_attempts_master": (1, 200),
        "daily_questions": (1, 100),
        "personalization_pool_limit": (10, 2000),
        "incorrect_carousel_size": (1, 30),
        "incorrect_window_attempts": (5, 500),
        "carousel_synonyms_limit": (0, 20),
        "carousel_antonyms_limit": (0, 20),
        "lecture_words": (1, 20),
    }
    float_fields = {
        "proficient_accuracy_threshold": (0.0, 100.0),
        "master_accuracy_threshold": (0.0, 100.0),
    }

    updated = {}

    try:
        for field, (low, high) in int_fields.items():
            if field in payload:
                value = int(payload[field])
                if value < low or value > high:
                    return jsonify({"error": f"{field} must be between {low} and {high}"}), 400
                updated[field] = value

        for field, (low, high) in float_fields.items():
            if field in payload:
                value = float(payload[field])
                if value < low or value > high:
                    return jsonify({"error": f"{field} must be between {low} and {high}"}), 400
                updated[field] = value
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid settings payload"}), 400

    if "min_attempts_master" in updated and "min_attempts_proficient" in updated:
        if updated["min_attempts_master"] < updated["min_attempts_proficient"]:
            return jsonify({"error": "min_attempts_master must be >= min_attempts_proficient"}), 400
    elif "min_attempts_master" in updated:
        if updated["min_attempts_master"] < APP_CONFIG["min_attempts_proficient"]:
            return jsonify({"error": "min_attempts_master must be >= min_attempts_proficient"}), 400
    elif "min_attempts_proficient" in updated:
        if APP_CONFIG["min_attempts_master"] < updated["min_attempts_proficient"]:
            return jsonify({"error": "min_attempts_master must be >= min_attempts_proficient"}), 400

    if "master_accuracy_threshold" in updated and "proficient_accuracy_threshold" in updated:
        if updated["master_accuracy_threshold"] < updated["proficient_accuracy_threshold"]:
            return jsonify({"error": "master_accuracy_threshold must be >= proficient_accuracy_threshold"}), 400
    elif "master_accuracy_threshold" in updated:
        if updated["master_accuracy_threshold"] < APP_CONFIG["proficient_accuracy_threshold"]:
            return jsonify({"error": "master_accuracy_threshold must be >= proficient_accuracy_threshold"}), 400
    elif "proficient_accuracy_threshold" in updated:
        if APP_CONFIG["master_accuracy_threshold"] < updated["proficient_accuracy_threshold"]:
            return jsonify({"error": "master_accuracy_threshold must be >= proficient_accuracy_threshold"}), 400

    APP_CONFIG.update(updated)
    return jsonify({"success": True, "settings": APP_CONFIG})


@app.route('/api/incorrect-carousel/<username>')
def incorrect_carousel(username):
    """Get recent incorrect words as carousel cards."""
    cards = build_incorrect_carousel(username)
    return jsonify({
        "username": username,
        "cards": cards,
        "count": len(cards),
        "config": {
            "size": APP_CONFIG["incorrect_carousel_size"],
            "window": APP_CONFIG["incorrect_window_attempts"],
            "synonyms_limit": APP_CONFIG["carousel_synonyms_limit"],
            "antonyms_limit": APP_CONFIG["carousel_antonyms_limit"],
        },
    })


@app.route('/api/projection/<username>')
def get_projection(username):
    """Get projected progress timeline for proficient/master milestones."""
    return jsonify(projected_progress(username))


@app.route('/api/lecture/<username>')
def get_lecture(username):
    """
    Build and return the pre-practice lecture for the user's active session.
    """
    session = get_or_create_practice_session(username)
    return jsonify({
        "username": username,
        "cards": session["lecture"],
        "count": len(session["lecture"]),
        "lectured_words": session["lecture_words"],
        "session_id": session["session_id"],
        "is_resumed": session["is_resumed"],
    })


@app.route('/api/practice-session/<username>')
def get_practice_session(username):
    """Create or resume a user's in-progress practice session."""
    force_new = request.args.get('new', '').lower() in {'1', 'true', 'yes'}
    return jsonify(get_or_create_practice_session(username, force_new=force_new))


@app.route('/api/daily-challenge')
def daily_challenge():
    """Get today's daily challenge (10 questions)."""
    if not challenge_gen:
        return jsonify({"error": "Challenge generator not initialized"}), 500

    username = request.args.get('username', 'guest')
    personalization = personalization_pool(
        build_level_dictionary(username),
        limit=APP_CONFIG["personalization_pool_limit"],
    )

    # Optional: bias questions toward words just lectured (passed as prefer=w1,w2,...)
    prefer_param = request.args.get('prefer', '')
    if prefer_param:
        lecture_words_list = [w.strip() for w in prefer_param.split(',') if w.strip()]
        # Merge lecture words at the front so they dominate the preferred pool
        seen = {w.lower() for w in lecture_words_list}
        preferred_words = lecture_words_list + [w for w in personalization if w.lower() not in seen]
    else:
        preferred_words = personalization

    question_count = int(request.args.get('num_questions', APP_CONFIG["daily_questions"]))
    questions = challenge_gen.generate_daily_challenge(
        num_questions=question_count,
        preferred_words=preferred_words if preferred_words else None,
    )

    return jsonify({
        "date": str(date.today()),
        "username": username,
        "questions": questions,
        "total": len(questions),
        "personalized": bool(preferred_words),
        "focus_words_count": len(preferred_words),
        "practicing_limit": APP_CONFIG["practicing_limit"],
    })

@app.route('/api/challenge/<challenge_type>')
def get_challenge(challenge_type):
    """Get a single challenge question."""
    if not challenge_gen:
        return jsonify({"error": "Challenge generator not initialized"}), 500
    
    difficulty = request.args.get('difficulty', 'medium')
    username = request.args.get('username', '')
    preferred_words = None
    if username:
        level_dict = build_level_dictionary(username)
        preferred_words = personalization_pool(
            level_dict,
            limit=APP_CONFIG["personalization_pool_limit"],
        )
    
    if challenge_type == 'synonym':
        question = challenge_gen.generate_synonym_match(difficulty, preferred_words=preferred_words)
    elif challenge_type == 'antonym':
        question = challenge_gen.generate_antonym_match(difficulty, preferred_words=preferred_words)
    else:
        return jsonify({"error": "Invalid challenge type"}), 400
    
    return jsonify(question)

@app.route('/api/validate', methods=['POST'])
def validate_answer():
    """Validate a user's answer."""
    if not challenge_gen:
        return jsonify({"error": "Challenge generator not initialized"}), 500
    
    data = request.json
    challenge = data.get('challenge')
    user_answer = data.get('answer')
    username = data.get('username', 'guest')
    
    result = challenge_gen.validate_answer(challenge, user_answer)
    
    # Save to database
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO challenge_history 
        (username, word, challenge_type, user_answer, correct_answer, is_correct)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        username,
        challenge['word'],
        challenge['type'],
        user_answer,
        challenge['correct_answer'],
        result['correct']
    ))
    conn.commit()
    conn.close()
    
    return jsonify(result)


def apply_progress_delta(username: str, score: int, total: int, conn=None) -> int:
    """Apply a daily progress delta and return the current streak."""
    owns_connection = conn is None
    if conn is None:
        conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    today = str(date.today())
    c.execute('''
        SELECT date, streak FROM user_progress
        WHERE username = ?
        ORDER BY date DESC
        LIMIT 1
    ''', (username,))

    last_entry = c.fetchone()
    streak = 1

    if last_entry:
        from datetime import datetime, timedelta
        last_date = datetime.strptime(last_entry[0], '%Y-%m-%d').date()
        today_date = datetime.strptime(today, '%Y-%m-%d').date()

        if (today_date - last_date).days == 1:
            streak = last_entry[1] + 1
        elif last_date == today_date:
            streak = last_entry[1]

    c.execute('''
        INSERT INTO user_progress (username, date, score, total_questions, streak)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(username, date) DO UPDATE SET
            score = score + ?,
            total_questions = total_questions + ?,
            streak = ?
    ''', (username, today, score, total, streak, score, total, streak))

    if owns_connection:
        conn.commit()
        conn.close()

    return streak


@app.route('/api/practice-session/<int:session_id>/answer', methods=['POST'])
def submit_session_answer(session_id):
    """Validate and persist one answer within a resumable practice session."""
    if not challenge_gen:
        return jsonify({"error": "Challenge generator not initialized"}), 500

    data = request.json or {}
    username = data.get('username', 'guest')
    user_answer = data.get('answer')
    question_index = int(data.get('question_index', -1))

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        SELECT username, questions_json, answers_json, is_completed
        FROM challenge_sessions
        WHERE id = ?
    ''', (session_id,))
    row = c.fetchone()

    if not row:
        conn.close()
        return jsonify({"error": "Practice session not found"}), 404

    session_username, questions_json, answers_json, is_completed = row
    if session_username != username:
        conn.close()
        return jsonify({"error": "Session/profile mismatch"}), 403

    questions = json.loads(questions_json)
    answers = normalize_session_answers(questions, json.loads(answers_json or '[]'))

    if question_index < 0 or question_index >= len(questions):
        conn.close()
        return jsonify({"error": "Invalid question index"}), 400

    if answers[question_index]:
        next_index = first_unanswered_index(answers)
        score = sum(1 for answer in answers if answer and answer.get('correct'))
        conn.close()
        stored = answers[question_index]
        return jsonify({
            "correct": stored.get("correct", False),
            "correct_answer": stored.get("correct_answer"),
            "explanation": stored.get("explanation", "Already answered."),
            "already_answered": True,
            "next_index": next_index,
            "answered_count": sum(1 for answer in answers if answer),
            "score": score,
            "session_completed": next_index >= len(questions),
        })

    challenge = questions[question_index]
    result = challenge_gen.validate_answer(challenge, user_answer)

    c.execute('''
        INSERT INTO challenge_history 
        (username, word, challenge_type, user_answer, correct_answer, is_correct)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        username,
        challenge['word'],
        challenge['type'],
        user_answer,
        challenge['correct_answer'],
        result['correct']
    ))

    streak = apply_progress_delta(username, 1 if result['correct'] else 0, 1, conn=conn)

    answers[question_index] = {
        "answer": user_answer,
        "correct": result['correct'],
        "correct_answer": result['correct_answer'],
        "explanation": result['explanation'],
    }
    next_index = first_unanswered_index(answers)
    completed = next_index >= len(questions)
    score = sum(1 for answer in answers if answer and answer.get('correct'))

    c.execute('''
        UPDATE challenge_sessions
        SET answers_json = ?,
            current_index = ?,
            is_completed = ?,
            updated_at = CURRENT_TIMESTAMP,
            completed_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE completed_at END
        WHERE id = ?
    ''', (
        json.dumps(answers, ensure_ascii=False),
        next_index,
        1 if completed else 0,
        1 if completed else 0,
        session_id,
    ))
    conn.commit()
    conn.close()

    return jsonify({
        **result,
        "already_answered": False,
        "next_index": next_index,
        "answered_count": sum(1 for answer in answers if answer),
        "score": score,
        "streak": streak,
        "session_completed": completed,
    })

@app.route('/api/progress/<username>')
def get_progress(username):
    """Get user's progress and statistics."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Get today's progress
    today = str(date.today())
    c.execute('''
        SELECT score, total_questions, streak
        FROM user_progress
        WHERE username = ? AND date = ?
    ''', (username, today))
    
    today_data = c.fetchone()
    
    # Get all-time stats
    c.execute('''
        SELECT 
            COUNT(*) as total_answered,
            SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct_count
        FROM challenge_history
        WHERE username = ?
    ''', (username,))
    
    all_time = c.fetchone()
    
    # Get recent history (last 7 days)
    c.execute('''
        SELECT date, score, total_questions
        FROM user_progress
        WHERE username = ?
        ORDER BY date DESC
        LIMIT 7
    ''', (username,))
    
    recent = c.fetchall()
    
    conn.close()
    
    return jsonify({
        "username": username,
        "today": {
            "score": today_data[0] if today_data else 0,
            "total": today_data[1] if today_data else 0,
            "streak": today_data[2] if today_data else 0
        },
        "all_time": {
            "total_answered": all_time[0] if all_time else 0,
            "correct": all_time[1] if all_time else 0,
            "accuracy": round(all_time[1] / all_time[0] * 100, 1) if all_time and all_time[0] > 0 else 0
        },
        "recent_days": [
            {"date": r[0], "score": r[1], "total": r[2]}
            for r in recent
        ]
    })


@app.route('/api/dashboard/<username>')
def dashboard(username):
    """Get dashboard data: latest exercises, results, trends, streaks, and word levels."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    today = str(date.today())

    c.execute('''
        SELECT score, total_questions, streak
        FROM user_progress
        WHERE username = ? AND date = ?
    ''', (username, today))
    today_data = c.fetchone()

    c.execute('''
        SELECT
            COUNT(*) as total_answered,
            SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct_count
        FROM challenge_history
        WHERE username = ?
    ''', (username,))
    all_time = c.fetchone()

    c.execute('''
        SELECT COALESCE(MAX(streak), 0)
        FROM user_progress
        WHERE username = ?
    ''', (username,))
    best_streak = c.fetchone()[0]

    c.execute('''
        SELECT
            word,
            challenge_type,
            user_answer,
            correct_answer,
            is_correct,
            timestamp
        FROM challenge_history
        WHERE username = ?
        ORDER BY timestamp DESC
        LIMIT 12
    ''', (username,))
    latest_exercises = c.fetchall()

    c.execute('''
        SELECT
            date(timestamp) as day,
            COUNT(*) as answered,
            SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct
        FROM challenge_history
        WHERE username = ?
        GROUP BY date(timestamp)
        ORDER BY day DESC
        LIMIT 14
    ''', (username,))
    trend_rows = c.fetchall()

    c.execute('''
        SELECT id, current_index, total_questions
        FROM challenge_sessions
        WHERE username = ? AND is_completed = 0
        ORDER BY id DESC
        LIMIT 1
    ''', (username,))
    active_session = c.fetchone()

    conn.close()

    total_answered = all_time[0] if all_time and all_time[0] else 0
    total_correct = all_time[1] if all_time and all_time[1] else 0
    all_time_accuracy = round((total_correct / total_answered) * 100, 1) if total_answered else 0

    level_dict = build_level_dictionary(username)
    vocab_count = len(vocab_data)
    words_stats = [
        {
            "word": word,
            "occurrences": meta["occurrences"],
            "correct": meta["correct"],
            "accuracy": meta["accuracy"],
            "level": meta["level"],
            "color": meta["color"],
        }
        for word, meta in level_dict.items()
    ]
    words_stats.sort(key=lambda item: (-item["occurrences"], item["word"]))

    words_covered = sum(1 for item in words_stats if item["occurrences"] > 0)
    coverage_pct = round((words_covered / vocab_count) * 100, 1) if vocab_count else 0

    level_counts = {
        "not-learned": sum(1 for item in words_stats if item["level"] == "not-learned"),
        "practicing": sum(1 for item in words_stats if item["level"] == "practicing"),
        "proficient": sum(1 for item in words_stats if item["level"] == "proficient"),
        "master": sum(1 for item in words_stats if item["level"] == "master"),
    }

    trend_days = [
        {
            "date": row[0],
            "answered": row[1],
            "correct": row[2] if row[2] else 0,
            "accuracy": round(((row[2] if row[2] else 0) / row[1]) * 100, 1) if row[1] else 0,
        }
        for row in trend_rows
    ]
    trend_days.reverse()

    return jsonify({
        "username": username,
        "latest_exercises": [
            {
                "word": row[0],
                "challenge_type": row[1],
                "user_answer": row[2],
                "correct_answer": row[3],
                "is_correct": bool(row[4]),
                "timestamp": row[5],
            }
            for row in latest_exercises
        ],
        "results": {
            "today": {
                "score": today_data[0] if today_data else 0,
                "total": today_data[1] if today_data else 0,
                "accuracy": round((today_data[0] / today_data[1]) * 100, 1) if today_data and today_data[1] else 0,
            },
            "all_time": {
                "total_answered": total_answered,
                "correct": total_correct,
                "accuracy": all_time_accuracy,
            },
        },
        "streaks": {
            "current": today_data[2] if today_data else 0,
            "best": best_streak,
        },
        "trends": trend_days,
        "word_coverage": {
            "total_vocab": vocab_count,
            "words_covered": words_covered,
            "coverage_pct": coverage_pct,
            "words": words_stats,
            "level_counts": level_counts,
        },
        "level_dict": level_dict,
        "level_policy": {
            "practicing_limit": APP_CONFIG["practicing_limit"],
            "levels": ["not-learned", "practicing", "proficient", "master"],
            "min_attempts_proficient": APP_CONFIG["min_attempts_proficient"],
            "min_attempts_master": APP_CONFIG["min_attempts_master"],
            "proficient_accuracy_threshold": APP_CONFIG["proficient_accuracy_threshold"],
            "master_accuracy_threshold": APP_CONFIG["master_accuracy_threshold"],
        },
        "active_challenge": {
            "exists": bool(active_session),
            "session_id": active_session[0] if active_session else None,
            "current_index": active_session[1] if active_session else 0,
            "total_questions": active_session[2] if active_session else 0,
        },
        "incorrect_carousel": build_incorrect_carousel(username),
        "projection": projected_progress(username),
    })

@app.route('/api/update-progress', methods=['POST'])
def update_progress():
    """Update user's daily progress."""
    data = request.json
    username = data.get('username', 'guest')
    score = data.get('score', 0)
    total = data.get('total', 0)
    streak = apply_progress_delta(username, score, total)

    return jsonify({"success": True, "streak": streak})

@app.route('/api/random-word')
def random_word():
    """Get a random vocabulary word with its data."""
    if not vocab_data:
        return jsonify({"error": "No vocabulary data loaded"}), 500
    
    word_data = random.choice(vocab_data)
    return jsonify(word_data)

@app.route('/api/word/<word>')
def get_word(word):
    """Get specific word data."""
    for word_data in vocab_data:
        if word_data['word'].lower() == word.lower():
            return jsonify(word_data)
    
    return jsonify({"error": "Word not found"}), 404


if __name__ == '__main__':
    print("\n" + "="*60)
    print("Vocab Deck - Web Interface Starting")
    print("="*60)
    
    if not api_key:
        print("\n⚠ WARNING: No API key configured!")
        print("Set MERRIAM_WEBSTER_API_KEY environment variable")
    
    if not vocab_data:
        print("\n⚠ WARNING: No enriched vocabulary data found!")
        print("Run: uv run read_vocab.py")
    else:
        print(f"\n✓ Loaded {len(vocab_data)} vocabulary words")
    
    print("\n🚀 Server starting at: http://localhost:5000")
    print("="*60 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
