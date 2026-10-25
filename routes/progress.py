import sqlite3
from datetime import date

from flask import Blueprint, jsonify, request

import state as ext
from database import apply_progress_delta
from services import (
    build_incorrect_carousel,
    build_level_dictionary,
    projected_progress,
)

progress_bp = Blueprint('progress', __name__)


@progress_bp.route('/api/projection/<username>')
def get_projection(username):
    return jsonify(projected_progress(username))


@progress_bp.route('/api/progress/<username>')
def get_progress(username):
    conn = sqlite3.connect(ext.DB_FILE)
    c = conn.cursor()

    today = str(date.today())
    c.execute('''
        SELECT score, total_questions, streak
        FROM user_progress
        WHERE username = ? AND date = ?
    ''', (username, today))
    today_data = c.fetchone()

    c.execute('''
        SELECT COUNT(*) as total_answered,
               SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct_count
        FROM challenge_history
        WHERE username = ?
    ''', (username,))
    all_time = c.fetchone()

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
            "streak": today_data[2] if today_data else 0,
        },
        "all_time": {
            "total_answered": all_time[0] if all_time else 0,
            "correct": all_time[1] if all_time else 0,
            "accuracy": round(all_time[1] / all_time[0] * 100, 1) if all_time and all_time[0] else 0,
        },
        "recent_days": [{"date": r[0], "score": r[1], "total": r[2]} for r in recent],
    })


@progress_bp.route('/api/dashboard/<username>')
def dashboard(username):
    conn = sqlite3.connect(ext.DB_FILE)
    c = conn.cursor()

    today = str(date.today())

    c.execute('''
        SELECT score, total_questions, streak
        FROM user_progress WHERE username = ? AND date = ?
    ''', (username, today))
    today_data = c.fetchone()

    c.execute('''
        SELECT COUNT(*) as total_answered,
               SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct_count
        FROM challenge_history WHERE username = ?
    ''', (username,))
    all_time = c.fetchone()

    c.execute('''
        SELECT COALESCE(MAX(streak), 0) FROM user_progress WHERE username = ?
    ''', (username,))
    best_streak = c.fetchone()[0]

    c.execute('''
        SELECT word, challenge_type, user_answer, correct_answer, is_correct, timestamp
        FROM challenge_history WHERE username = ?
        ORDER BY timestamp DESC LIMIT 12
    ''', (username,))
    latest_exercises = c.fetchall()

    c.execute('''
        SELECT date(timestamp) as day,
               COUNT(*) as answered,
               SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct
        FROM challenge_history WHERE username = ?
        GROUP BY date(timestamp)
        ORDER BY day DESC LIMIT 14
    ''', (username,))
    trend_rows = c.fetchall()

    c.execute('''
        SELECT id, current_index, total_questions
        FROM challenge_sessions
        WHERE username = ? AND is_completed = 0
        ORDER BY id DESC LIMIT 1
    ''', (username,))
    active_session = c.fetchone()
    conn.close()

    total_answered = all_time[0] if all_time and all_time[0] else 0
    total_correct = all_time[1] if all_time and all_time[1] else 0
    all_time_accuracy = round((total_correct / total_answered) * 100, 1) if total_answered else 0

    level_dict = build_level_dictionary(username)
    vocab_count = len(ext.vocab_data)
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
            "correct": row[2] or 0,
            "accuracy": round(((row[2] or 0) / row[1]) * 100, 1) if row[1] else 0,
        }
        for row in reversed(trend_rows)
    ]

    return jsonify({
        "username": username,
        "latest_exercises": [
            {
                "word": row[0], "challenge_type": row[1],
                "user_answer": row[2], "correct_answer": row[3],
                "is_correct": bool(row[4]), "timestamp": row[5],
            }
            for row in latest_exercises
        ],
        "results": {
            "today": {
                "score": today_data[0] if today_data else 0,
                "total": today_data[1] if today_data else 0,
                "accuracy": round((today_data[0] / today_data[1]) * 100, 1) if today_data and today_data[1] else 0,
            },
            "all_time": {"total_answered": total_answered, "correct": total_correct, "accuracy": all_time_accuracy},
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
            "practicing_limit": ext.APP_CONFIG["practicing_limit"],
            "levels": ["not-learned", "practicing", "proficient", "master"],
            "min_attempts_proficient": ext.APP_CONFIG["min_attempts_proficient"],
            "min_attempts_master": ext.APP_CONFIG["min_attempts_master"],
            "proficient_accuracy_threshold": ext.APP_CONFIG["proficient_accuracy_threshold"],
            "master_accuracy_threshold": ext.APP_CONFIG["master_accuracy_threshold"],
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


@progress_bp.route('/api/update-progress', methods=['POST'])
def update_progress():
    data = request.json
    username = data.get('username', 'guest')
    score = data.get('score', 0)
    total = data.get('total', 0)
    streak = apply_progress_delta(username, score, total)
    return jsonify({"success": True, "streak": streak})
