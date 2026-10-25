"""
Database initialization and low-level write helpers.
"""

import sqlite3
from datetime import date, datetime

import state as ext


def init_db() -> None:
    conn = sqlite3.connect(ext.DB_FILE)
    c = conn.cursor()

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

    c.execute('''
        CREATE TABLE IF NOT EXISTS srs_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            word TEXT NOT NULL,
            quality INTEGER NOT NULL,
            interval_days INTEGER NOT NULL DEFAULT 1,
            repetitions INTEGER NOT NULL DEFAULT 0,
            ef REAL NOT NULL DEFAULT 2.5,
            next_review_date TEXT NOT NULL,
            rated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(username, word)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS reading_passages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            passage TEXT NOT NULL,
            words_json TEXT NOT NULL,
            words_key TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(words_key)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS passage_words (
            passage_id INTEGER NOT NULL REFERENCES reading_passages(id) ON DELETE CASCADE,
            word TEXT NOT NULL
        )
    ''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_passage_words_word ON passage_words(word)')

    # Migration: add questions_json for GRE RC exercises (idempotent)
    try:
        c.execute("ALTER TABLE reading_passages ADD COLUMN questions_json TEXT NOT NULL DEFAULT '[]'")
    except sqlite3.OperationalError:
        pass  # column already exists

    c.execute('''
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')

    conn.commit()
    conn.close()


def load_settings_from_db() -> dict[str, int | float]:
    conn = sqlite3.connect(ext.DB_FILE)
    c = conn.cursor()
    c.execute('SELECT key, value FROM app_settings')
    rows = c.fetchall()
    conn.close()

    result: dict = {}
    for key, raw_value in rows:
        default = ext.APP_CONFIG.get(key)
        if isinstance(default, int):
            result[key] = int(raw_value)
        elif isinstance(default, float):
            result[key] = float(raw_value)
        # skip unknown keys
    return result


def save_settings_to_db(settings: dict) -> None:
    conn = sqlite3.connect(ext.DB_FILE)
    c = conn.cursor()
    for key, value in settings.items():
        c.execute('''
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        ''', (key, str(value)))
    conn.commit()
    conn.close()


def get_active_session_row(username: str):
    conn = sqlite3.connect(ext.DB_FILE)
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


def apply_progress_delta(username: str, score: int, total: int, conn=None) -> int:
    owns_connection = conn is None
    if conn is None:
        conn = sqlite3.connect(ext.DB_FILE)
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
