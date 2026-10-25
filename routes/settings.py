import random

from flask import Blueprint, jsonify, request

import state as ext
from database import save_settings_to_db

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/api/status')
def api_status():
    return jsonify({
        "status": "ok",
        "source": ext.SOURCE_KEY,
        "data_file": ext.ENRICHED_FILE.name,
        "api_key_configured": ext.thesaurus is not None,
        "vocab_loaded": len(ext.vocab_data) > 0,
        "vocab_count": len(ext.vocab_data),
        "challenge_ready": ext.challenge_gen is not None,
        "config": ext.APP_CONFIG,
    })


@settings_bp.route('/api/settings', methods=['GET'])
def get_settings():
    return jsonify({"settings": ext.APP_CONFIG})


@settings_bp.route('/api/settings', methods=['POST'])
def update_settings():
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

    updated: dict = {}
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
        if updated["min_attempts_master"] < ext.APP_CONFIG["min_attempts_proficient"]:
            return jsonify({"error": "min_attempts_master must be >= min_attempts_proficient"}), 400
    elif "min_attempts_proficient" in updated:
        if ext.APP_CONFIG["min_attempts_master"] < updated["min_attempts_proficient"]:
            return jsonify({"error": "min_attempts_master must be >= min_attempts_proficient"}), 400

    if "master_accuracy_threshold" in updated and "proficient_accuracy_threshold" in updated:
        if updated["master_accuracy_threshold"] < updated["proficient_accuracy_threshold"]:
            return jsonify({"error": "master_accuracy_threshold must be >= proficient_accuracy_threshold"}), 400
    elif "master_accuracy_threshold" in updated:
        if updated["master_accuracy_threshold"] < ext.APP_CONFIG["proficient_accuracy_threshold"]:
            return jsonify({"error": "master_accuracy_threshold must be >= proficient_accuracy_threshold"}), 400
    elif "proficient_accuracy_threshold" in updated:
        if ext.APP_CONFIG["master_accuracy_threshold"] < updated["proficient_accuracy_threshold"]:
            return jsonify({"error": "master_accuracy_threshold must be >= proficient_accuracy_threshold"}), 400

    ext.APP_CONFIG.update(updated)
    save_settings_to_db(ext.APP_CONFIG)
    return jsonify({"success": True, "settings": ext.APP_CONFIG})


@settings_bp.route('/api/profiles')
def list_profiles():
    import sqlite3

    from services import build_level_dictionary

    conn = sqlite3.connect(ext.DB_FILE)
    c = conn.cursor()
    c.execute('''
        SELECT DISTINCT username FROM user_progress
        UNION
        SELECT DISTINCT username FROM challenge_history
        ORDER BY username
    ''')
    usernames = [row[0] for row in c.fetchall()]
    conn.close()

    total_vocab = len(ext.vocab_data)
    profiles = []
    for uname in usernames:
        level_dict = build_level_dictionary(uname)
        counts: dict = {"not-learned": 0, "practicing": 0, "proficient": 0, "master": 0}
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


@settings_bp.route('/api/random-word')
def random_word():
    if not ext.vocab_data:
        return jsonify({"error": "No vocabulary data loaded"}), 500
    return jsonify(random.choice(ext.vocab_data))


@settings_bp.route('/api/word/<word>')
def get_word(word):
    for entry in ext.vocab_data:
        if entry['word'].lower() == word.lower():
            return jsonify(entry)
    return jsonify({"error": "Word not found"}), 404
