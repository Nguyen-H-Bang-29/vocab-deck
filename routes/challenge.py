import json
import sqlite3
from datetime import date

from flask import Blueprint, jsonify, request

import state as ext
from database import apply_progress_delta
from services import (
    build_incorrect_carousel,
    build_level_dictionary,
    first_unanswered_index,
    get_or_create_practice_session,
    normalize_session_answers,
    personalization_pool,
)

challenge_bp = Blueprint('challenge', __name__)


@challenge_bp.route('/api/lecture/<username>')
def get_lecture(username):
    session = get_or_create_practice_session(username)
    return jsonify({
        "username": username,
        "cards": session["lecture"],
        "count": len(session["lecture"]),
        "lectured_words": session["lecture_words"],
        "session_id": session["session_id"],
        "is_resumed": session["is_resumed"],
    })


@challenge_bp.route('/api/incorrect-carousel/<username>')
def incorrect_carousel(username):
    cards = build_incorrect_carousel(username)
    return jsonify({
        "username": username,
        "cards": cards,
        "count": len(cards),
        "config": {
            "size": ext.APP_CONFIG["incorrect_carousel_size"],
            "window": ext.APP_CONFIG["incorrect_window_attempts"],
            "synonyms_limit": ext.APP_CONFIG["carousel_synonyms_limit"],
            "antonyms_limit": ext.APP_CONFIG["carousel_antonyms_limit"],
        },
    })


@challenge_bp.route('/api/daily-challenge')
def daily_challenge():
    if not ext.challenge_gen:
        return jsonify({"error": "Challenge generator not initialized"}), 500

    username = request.args.get('username', 'guest')
    personalization = personalization_pool(
        build_level_dictionary(username),
        limit=ext.APP_CONFIG["personalization_pool_limit"],
    )

    prefer_param = request.args.get('prefer', '')
    if prefer_param:
        lecture_words_list = [w.strip() for w in prefer_param.split(',') if w.strip()]
        seen = {w.lower() for w in lecture_words_list}
        preferred_words = lecture_words_list + [w for w in personalization if w.lower() not in seen]
    else:
        preferred_words = personalization

    question_count = int(request.args.get('num_questions', ext.APP_CONFIG["daily_questions"]))
    questions = ext.challenge_gen.generate_daily_challenge(
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
        "practicing_limit": ext.APP_CONFIG["practicing_limit"],
    })


@challenge_bp.route('/api/challenge/<challenge_type>')
def get_challenge(challenge_type):
    if not ext.challenge_gen:
        return jsonify({"error": "Challenge generator not initialized"}), 500

    difficulty = request.args.get('difficulty', 'medium')
    username = request.args.get('username', '')
    preferred_words = None
    if username:
        level_dict = build_level_dictionary(username)
        preferred_words = personalization_pool(
            level_dict, limit=ext.APP_CONFIG["personalization_pool_limit"]
        )

    if challenge_type == 'synonym':
        question = ext.challenge_gen.generate_synonym_match(difficulty, preferred_words=preferred_words)
    elif challenge_type == 'antonym':
        question = ext.challenge_gen.generate_antonym_match(difficulty, preferred_words=preferred_words)
    else:
        return jsonify({"error": "Invalid challenge type"}), 400

    return jsonify(question)


@challenge_bp.route('/api/validate', methods=['POST'])
def validate_answer():
    if not ext.challenge_gen:
        return jsonify({"error": "Challenge generator not initialized"}), 500

    data = request.json
    challenge = data.get('challenge')
    user_answer = data.get('answer')
    username = data.get('username', 'guest')

    result = ext.challenge_gen.validate_answer(challenge, user_answer)

    conn = sqlite3.connect(ext.DB_FILE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO challenge_history
            (username, word, challenge_type, user_answer, correct_answer, is_correct)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (username, challenge['word'], challenge['type'], user_answer,
          challenge['correct_answer'], result['correct']))
    conn.commit()
    conn.close()

    return jsonify(result)


@challenge_bp.route('/api/practice-session/<username>')
def get_practice_session(username):
    force_new = request.args.get('new', '').lower() in {'1', 'true', 'yes'}
    return jsonify(get_or_create_practice_session(username, force_new=force_new))


@challenge_bp.route('/api/practice-session/<int:session_id>/answer', methods=['POST'])
def submit_session_answer(session_id):
    if not ext.challenge_gen:
        return jsonify({"error": "Challenge generator not initialized"}), 500

    data = request.json or {}
    username = data.get('username', 'guest')
    user_answer = data.get('answer')
    question_index = int(data.get('question_index', -1))

    conn = sqlite3.connect(ext.DB_FILE)
    c = conn.cursor()
    c.execute('''
        SELECT username, questions_json, answers_json, is_completed
        FROM challenge_sessions WHERE id = ?
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
        score = sum(1 for a in answers if a and a.get('correct'))
        conn.close()
        stored = answers[question_index]
        return jsonify({
            "correct": stored.get("correct", False),
            "correct_answer": stored.get("correct_answer"),
            "explanation": stored.get("explanation", "Already answered."),
            "already_answered": True,
            "next_index": next_index,
            "answered_count": sum(1 for a in answers if a),
            "score": score,
            "session_completed": next_index >= len(questions),
        })

    challenge = questions[question_index]
    result = ext.challenge_gen.validate_answer(challenge, user_answer)

    c.execute('''
        INSERT INTO challenge_history
            (username, word, challenge_type, user_answer, correct_answer, is_correct)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (username, challenge['word'], challenge['type'], user_answer,
          challenge['correct_answer'], result['correct']))

    streak = apply_progress_delta(username, 1 if result['correct'] else 0, 1, conn=conn)

    answers[question_index] = {
        "answer": user_answer,
        "correct": result['correct'],
        "correct_answer": result['correct_answer'],
        "explanation": result['explanation'],
    }
    next_index = first_unanswered_index(answers)
    completed = next_index >= len(questions)
    score = sum(1 for a in answers if a and a.get('correct'))

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
        "answered_count": sum(1 for a in answers if a),
        "score": score,
        "streak": streak,
        "session_completed": completed,
    })
