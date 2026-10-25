"""
Business logic helpers — leveling, session management, and content building.
"""

import json
import math
import sqlite3
from datetime import date, datetime, timedelta
from typing import TypedDict

import state as ext
from database import get_active_session_row


class _WordStats(TypedDict):
    raw_count: int
    raw_correct: int
    w_total: float
    w_correct: float


# ── SM-2 ──────────────────────────────────────────────────────────────────────

def sm2_next(
    quality: int,
    repetitions: int,
    interval: int,
    ef: float,
) -> tuple[int, int, float, str]:
    """One SM-2 step. quality ∈ {1..5} (1=blackout, 5=perfect).

    Returns (new_interval_days, new_repetitions, new_ef, next_review_iso).
    Reference: Wozniak 1987, https://www.supermemo.com/en/archives1990-2015/english/ol/sm2
    """
    ef_new = max(1.3, ef + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    if quality < 3:
        interval_new, reps_new = 1, 0
    else:
        if repetitions == 0:
            interval_new = 1
        elif repetitions == 1:
            interval_new = 6
        else:
            interval_new = round(interval * ef_new)
        reps_new = repetitions + 1
    next_date = (date.today() + timedelta(days=interval_new)).isoformat()
    return interval_new, reps_new, ef_new, next_date


# ── Leveling ───────────────────────────────────────────────────────────────────

def classify_level_from_history(accuracy: float, attempts: int) -> dict:
    cfg = ext.APP_CONFIG
    if attempts == 0:
        return {"level": "not-learned", "color": "#9e9e9e"}
    if attempts >= cfg["min_attempts_master"] and accuracy >= cfg["master_accuracy_threshold"]:
        return {"level": "master", "color": "#4caf50"}
    if attempts >= cfg["min_attempts_proficient"] and accuracy >= cfg["proficient_accuracy_threshold"]:
        return {"level": "proficient", "color": "#2196f3"}
    return {"level": "practicing", "color": "#ff9800"}


# Weight halves every 14 days so recent attempts dominate level classification.
_DECAY_HALF_LIFE = 14.0


def build_level_dictionary(username: str) -> dict:
    conn = sqlite3.connect(ext.DB_FILE)
    c = conn.cursor()
    c.execute(
        'SELECT word, is_correct, timestamp FROM challenge_history WHERE username = ?',
        (username,),
    )
    rows = c.fetchall()
    c.execute(
        'SELECT word FROM srs_ratings WHERE username = ? AND quality = 5',
        (username,),
    )
    # Words the user has explicitly rated "Easy" during SRS review are treated
    # as already known — they're bumped straight to master regardless of quiz
    # history, and personalization_pool() excludes them outright.
    srs_mastered: set[str] = {row[0].lower() for row in c.fetchall()}
    conn.close()

    now = datetime.now()
    word_stats: dict[str, _WordStats] = {}
    for word, is_correct, ts_str in rows:
        key = word.lower()
        if key not in word_stats:
            word_stats[key] = {'raw_count': 0, 'raw_correct': 0, 'w_total': 0.0, 'w_correct': 0.0}
        try:
            ts = datetime.fromisoformat(ts_str.replace(' ', 'T'))
            age_days = (now - ts).total_seconds() / 86400.0
        except (ValueError, TypeError):
            age_days = 0.0
        w = math.pow(0.5, age_days / _DECAY_HALF_LIFE)
        word_stats[key]['raw_count'] += 1
        word_stats[key]['w_total'] += w
        if is_correct:
            word_stats[key]['raw_correct'] += 1
            word_stats[key]['w_correct'] += w

    level_dict: dict = {}
    for entry in ext.vocab_data:
        word = entry.get("word", "")
        if not word:
            continue
        if (stats := word_stats.get(word.lower())) is not None:
            raw_count: int = stats['raw_count']
            raw_correct: int = stats['raw_correct']
            w_total: float = stats['w_total']
            w_correct: float = stats['w_correct']
        else:
            raw_count = 0
            raw_correct = 0
            w_total = 0.0
            w_correct = 0.0

        # Raw values shown in the UI; decayed accuracy drives level classification.
        raw_accuracy = round((raw_correct / raw_count) * 100, 1) if raw_count else 0.0
        decayed_accuracy = round((w_correct / w_total) * 100, 1) if w_total else 0.0

        is_srs_mastered = word.lower() in srs_mastered
        cls = {"level": "master", "color": "#4caf50"} if is_srs_mastered else classify_level_from_history(decayed_accuracy, raw_count)
        level_dict[word] = {
            "occurrences": raw_count,
            "correct": raw_correct,
            "accuracy": raw_accuracy,
            "level": cls["level"],
            "color": cls["color"],
            "word_type": entry.get("word_type", ""),
            "srs_mastered": is_srs_mastered,
        }

    return level_dict


def personalization_pool(level_dict: dict, limit: int = 180) -> list:
    if not level_dict:
        return []

    # SRS-mastered words ("Easy" during review) are excluded outright, not
    # just deprioritized — they never resurface, even as reinforcement filler.
    ordered = [
        w for e in ext.vocab_data
        if (w := e.get("word")) and not level_dict.get(w, {}).get("srs_mastered")
    ]
    cfg = ext.APP_CONFIG

    practicing = [w for w in ordered if level_dict.get(w, {}).get("level") == "practicing"]
    not_learned = [w for w in ordered if level_dict.get(w, {}).get("level") == "not-learned"]
    reinforcement = [w for w in ordered if level_dict.get(w, {}).get("level") in {"proficient", "master"}]

    available_slots = max(0, cfg["practicing_limit"] - len(practicing))
    focus_pool = practicing + not_learned[:available_slots]
    if len(focus_pool) < limit:
        focus_pool.extend(reinforcement[:limit - len(focus_pool)])

    return focus_pool[:limit]


def projected_progress(username: str) -> dict:
    level_dict = build_level_dictionary(username)
    total_vocab = len(ext.vocab_data)

    if total_vocab == 0:
        return {
            "username": username,
            "total_vocab": 0,
            "daily_questions": ext.APP_CONFIG["daily_questions"],
            "projections": {"proficient": [], "master": []},
        }

    proficient_now = sum(1 for m in level_dict.values() if m["level"] in {"proficient", "master"})
    master_now = sum(1 for m in level_dict.values() if m["level"] == "master")

    dq = ext.APP_CONFIG["daily_questions"]
    pl = ext.APP_CONFIG["practicing_limit"]
    prof_velocity = max(0.25, min(dq, pl) * 0.12)
    master_velocity = max(0.12, min(dq, pl) * 0.06)
    targets = [50, 75, 90]

    def eta(current: int, target_pct: int, velocity: float) -> int:
        remaining = max(0, int(target_pct / 100 * total_vocab) - current)
        return 0 if remaining == 0 else int(remaining / velocity + 0.999)

    return {
        "username": username,
        "total_vocab": total_vocab,
        "daily_questions": dq,
        "projections": {
            "proficient": [
                {"target_percent": t, "target_words": int(t / 100 * total_vocab),
                 "current_words": proficient_now, "eta_days": eta(proficient_now, t, prof_velocity)}
                for t in targets
            ],
            "master": [
                {"target_percent": t, "target_words": int(t / 100 * total_vocab),
                 "current_words": master_now, "eta_days": eta(master_now, t, master_velocity)}
                for t in targets
            ],
        },
    }


# ── Vocab lookup ───────────────────────────────────────────────────────────────

def vocab_lookup_map() -> dict:
    return {item.get("word", "").lower(): item for item in ext.vocab_data if item.get("word")}


# ── Session / lecture helpers ─────────────────────────────────────────────────

def lecture_cards_for_words(words: list[str]) -> list:
    lookup = vocab_lookup_map()
    cfg = ext.APP_CONFIG
    cards = []

    for word in words:
        entry = lookup.get((word or "").lower(), {})
        raw_senses = entry.get("senses")
        if raw_senses:
            senses = [
                {
                    "word_type": s.get("word_type", ""),
                    "definition": s.get("definition", ""),
                    "synonyms": (s.get("synonyms") or [])[:cfg["carousel_synonyms_limit"]],
                    "antonyms": (s.get("antonyms") or [])[:cfg["carousel_antonyms_limit"]],
                }
                for s in raw_senses[:6]
            ]
        else:
            senses = [{
                "word_type": entry.get("word_type", ""),
                "definition": entry.get("definition", "Definition unavailable"),
                "synonyms": (entry.get("synonyms") or [])[:cfg["carousel_synonyms_limit"]],
                "antonyms": (entry.get("antonyms") or [])[:cfg["carousel_antonyms_limit"]],
            }]

        cards.append({
            "word": word,
            "word_type": entry.get("word_type") or (senses[0]["word_type"] if senses else ""),
            "senses": senses,
        })

    return cards


def unique_words_in_questions(questions: list[dict]) -> list[str]:
    seen: set = set()
    ordered: list[str] = []
    for q in (questions or []):
        word = (q or {}).get("word", "")
        key = word.lower()
        if word and key not in seen:
            seen.add(key)
            ordered.append(word)
    return ordered


def normalize_session_answers(questions: list[dict], answers: list | None) -> list:
    normalized = list(answers or [])[:len(questions)]
    if len(normalized) < len(questions):
        normalized.extend([None] * (len(questions) - len(normalized)))
    return normalized


def first_unanswered_index(answers: list) -> int:
    for idx, answer in enumerate(answers):
        if not answer:
            return idx
    return len(answers)


def generate_personalized_questions(username: str, num_questions: int | None = None) -> list[dict]:
    level_dict = build_level_dictionary(username)
    preferred = personalization_pool(level_dict, limit=ext.APP_CONFIG["personalization_pool_limit"])
    count = num_questions or ext.APP_CONFIG["daily_questions"]
    return ext.challenge_gen.generate_daily_challenge(
        num_questions=count,
        preferred_words=preferred if preferred else None,
    )


def serialize_session_payload(
    session_id: int,
    username: str,
    questions: list[dict],
    answers: list,
) -> dict:
    answers = normalize_session_answers(questions, answers)
    current_index = first_unanswered_index(answers)
    lecture_words = unique_words_in_questions(questions)
    score = sum(1 for a in answers if a and a.get("correct"))
    answered_count = sum(1 for a in answers if a)

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


def get_or_create_practice_session(username: str, force_new: bool = False) -> dict:
    row = None if force_new else get_active_session_row(username)
    if row:
        session_id, questions_json, answers_json = row
        questions = json.loads(questions_json)
        answers = json.loads(answers_json or "[]")
        return serialize_session_payload(session_id, username, questions, answers)

    questions = generate_personalized_questions(username)
    answers: list = [None] * len(questions)

    conn = sqlite3.connect(ext.DB_FILE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO challenge_sessions
            (username, questions_json, answers_json, current_index, total_questions, is_completed)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        username,
        json.dumps(questions, ensure_ascii=False),
        json.dumps(answers, ensure_ascii=False),
        0, len(questions), 0,
    ))
    session_id = c.lastrowid
    conn.commit()
    conn.close()

    return serialize_session_payload(session_id, username, questions, answers)


def build_incorrect_carousel(username: str) -> list:
    if not ext.vocab_data:
        return []

    conn = sqlite3.connect(ext.DB_FILE)
    c = conn.cursor()
    c.execute('''
        SELECT word, timestamp
        FROM challenge_history
        WHERE username = ? AND is_correct = 0
        ORDER BY timestamp DESC
        LIMIT ?
    ''', (username, ext.APP_CONFIG["incorrect_window_attempts"]))
    rows = c.fetchall()
    conn.close()

    lookup = vocab_lookup_map()
    cfg = ext.APP_CONFIG
    seen: set = set()
    cards: list = []

    for word, ts in rows:
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)

        entry = lookup.get(key, {})
        raw_senses = entry.get("senses")
        if raw_senses:
            trimmed = [
                {
                    "word_type": s.get("word_type", ""),
                    "definition": s.get("definition", ""),
                    "synonyms": (s.get("synonyms") or [])[:cfg["carousel_synonyms_limit"]],
                    "antonyms": (s.get("antonyms") or [])[:cfg["carousel_antonyms_limit"]],
                }
                for s in raw_senses[:6]
            ]
        else:
            trimmed = [{
                "word_type": entry.get("word_type", ""),
                "definition": entry.get("definition", "Definition unavailable"),
                "synonyms": (entry.get("synonyms") or [])[:cfg["carousel_synonyms_limit"]],
                "antonyms": (entry.get("antonyms") or [])[:cfg["carousel_antonyms_limit"]],
            }]

        cards.append({
            "word": word,
            "timestamp": ts,
            "word_type": entry.get("word_type") or (trimmed[0]["word_type"] if trimmed else ""),
            "senses": trimmed,
        })

        if len(cards) >= cfg["incorrect_carousel_size"]:
            break

    return cards
