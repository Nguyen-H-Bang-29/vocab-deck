import sqlite3

from flask import Blueprint, jsonify, request

import state as ext
from services import sm2_next

srs_bp = Blueprint('srs', __name__)


@srs_bp.route('/api/srs/rate', methods=['POST'])
def srs_rate():
    """Record a SM-2 confidence rating and update the word's review schedule.

    Body: { username, word, quality }  quality ∈ {1,3,4,5}
      1 = Again (forgot), 3 = Hard, 4 = Good, 5 = Easy
    """
    data = request.json or {}
    username: str = data.get('username', 'guest')
    word: str = (data.get('word') or '').strip()
    quality_raw = data.get('quality')

    if not word:
        return jsonify({"error": "word is required"}), 400
    try:
        quality = int(quality_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "quality must be an integer"}), 400
    if quality not in {1, 2, 3, 4, 5}:
        return jsonify({"error": "quality must be 1–5"}), 400

    conn = sqlite3.connect(ext.DB_FILE)
    c = conn.cursor()
    c.execute(
        'SELECT interval_days, repetitions, ef FROM srs_ratings WHERE username=? AND word=?',
        (username, word),
    )
    row = c.fetchone()
    prev_interval, prev_reps, prev_ef = (row[0], row[1], row[2]) if row else (1, 0, 2.5)

    interval_new, reps_new, ef_new, next_date = sm2_next(quality, prev_reps, prev_interval, prev_ef)

    c.execute('''
        INSERT INTO srs_ratings (username, word, quality, interval_days, repetitions, ef, next_review_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(username, word) DO UPDATE SET
            quality          = excluded.quality,
            interval_days    = excluded.interval_days,
            repetitions      = excluded.repetitions,
            ef               = excluded.ef,
            next_review_date = excluded.next_review_date,
            rated_at         = CURRENT_TIMESTAMP
    ''', (username, word, quality, interval_new, reps_new, ef_new, next_date))
    conn.commit()
    conn.close()

    return jsonify({
        "word": word,
        "interval_days": interval_new,
        "next_review_date": next_date,
        "repetitions": reps_new,
        "ef": round(ef_new, 3),
    })
