import json
import random
import sqlite3
import time
from typing import Any, cast

from flask import Blueprint, jsonify, request

import state as ext

passage_bp = Blueprint('passage', __name__)

# Per-username cooldown: only the Claude call is throttled.
# Cached hits bypass this check entirely.
_last_generation: dict[str, float] = {}
_COOLDOWN_SECONDS = 60  # 1 minute between Claude calls per username

_GRE_EXERCISE_TOOL: dict[str, Any] = {
    "name": "create_gre_exercise",
    "description": "Create a GRE reading comprehension exercise using the given vocabulary words.",
    "input_schema": {
        "type": "object",
        "properties": {
            "passage": {
                "type": "string",
                "description": "140-160 word academic passage that uses all vocabulary words naturally.",
            },
            "questions": {
                "type": "array",
                "description": "Exactly 3 comprehension questions.",
                "minItems": 3,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "choices": {
                            "type": "array",
                            "description": "Four answer choices labeled (A)–(D).",
                            "minItems": 4,
                            "maxItems": 4,
                            "items": {"type": "string"},
                        },
                        "correct_index": {
                            "type": "integer",
                            "description": "0-based index of the correct choice.",
                            "minimum": 0,
                            "maximum": 3,
                        },
                        "explanation": {
                            "type": "string",
                            "description": "1-2 sentence explanation of why the answer is correct.",
                        },
                    },
                    "required": ["question", "choices", "correct_index", "explanation"],
                },
            },
        },
        "required": ["passage", "questions"],
    },
}


@passage_bp.route('/api/reading-passage', methods=['POST'])
def generate_reading_passage() -> Any:
    """Generate (or return cached) a GRE reading comprehension exercise.

    Exact-match cache: same word set → same passage/questions, no API call.
    Pass `regenerate: true` to force a fresh Claude call and replace the
    cached entry (still subject to the per-username throttle below).
    Uncached requests are throttled per username to avoid Claude overuse.
    Returns 503 if ANTHROPIC_API_KEY is not configured.
    """
    if not ext.anthropic_client:
        return jsonify({"error": "passage_unavailable", "reason": "ANTHROPIC_API_KEY not configured"}), 503

    data = cast(dict[str, Any], request.get_json(silent=True) or {})
    raw_words: Any = data.get('words', [])
    username: str = str(data.get('username', 'anonymous')).strip() or 'anonymous'
    regenerate: bool = data.get('regenerate') is True

    if not raw_words or not isinstance(raw_words, list):
        return jsonify({"error": "words list is required"}), 400

    words: list[str] = [str(w).strip() for w in raw_words if str(w).strip()][:15]
    if not words:
        return jsonify({"error": "no valid words provided"}), 400

    valid_vocab: set[str] = {
        str(entry.get('word', '')).lower()
        for entry in ext.vocab_data
        if entry.get('word')
    }
    unknown = [w for w in words if w.lower() not in valid_vocab]
    if unknown:
        return jsonify({"error": "unknown_words", "words": unknown}), 400

    words_key = ','.join(sorted(w.lower() for w in words))

    conn = sqlite3.connect(ext.DB_FILE)
    c = conn.cursor()

    c.execute(
        'SELECT id, passage, questions_json FROM reading_passages WHERE words_key = ?',
        (words_key,),
    )
    cached = c.fetchone()
    if cached:
        cached_id, cached_passage, cached_q_json = cached
        cached_questions: list = json.loads(cached_q_json or '[]')
        if cached_questions and not regenerate:
            conn.close()
            return jsonify({
                "passage": cached_passage,
                "questions": cached_questions,
                "words": words,
                "cached": True,
            })
        # Forced regeneration, or an old entry without questions — evict so
        # the INSERT below doesn't collide with the existing words_key row.
        c.execute('DELETE FROM passage_words WHERE passage_id = ?', (cached_id,))
        c.execute('DELETE FROM reading_passages WHERE id = ?', (cached_id,))
        conn.commit()

    conn.close()

    # Throttle only the Claude call, not cached responses.
    # `last` must default to None (not 0.0): time.monotonic()'s epoch is
    # unspecified and can sit near machine-boot time (e.g. Fly.io cold
    # starts), so a 0.0 default would make "seconds since boot" look like
    # "seconds since last generation" and falsely throttle a user's very
    # first request.
    now = time.monotonic()
    last = _last_generation.get(username)
    if last is not None and now - last < _COOLDOWN_SECONDS:
        retry_after = int(_COOLDOWN_SECONDS - (now - last))
        return jsonify({"error": "rate_limited", "retry_after": retry_after}), 429

    word_list = ', '.join(words)
    prompt = (
        f"Vocabulary words to use: {word_list}\n\n"
        "Create a GRE reading comprehension exercise:\n"
        "- Passage: 140-160 words, academic tone, uses ALL vocabulary words naturally\n"
        "- Q1: meaning of one vocabulary word as used in the passage\n"
        "- Q2: an inference or implication drawn from the passage\n"
        "- Q3: the main idea or author's purpose\n"
        "- Each question has exactly 4 choices labeled (A), (B), (C), (D)"
    )

    try:
        message = ext.anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1200,
            tools=[_GRE_EXERCISE_TOOL],
            tool_choice={"type": "tool", "name": "create_gre_exercise"},
            messages=[{"role": "user", "content": prompt}],
        )
        tool_block = next(
            (b for b in message.content if b.type == "tool_use"),
            None,
        )
        if tool_block is None:
            ext.logger.error("RC passage: no tool_use block in response")
            return jsonify({"error": "generation_failed"}), 500

        result: dict[str, Any] = cast(Any, tool_block).input
        passage: str = str(result.get('passage', '')).strip()

        questions: list[dict[str, Any]] = []
        for q in cast(list[Any], result.get('questions') or []):
            q_dict = cast(dict[str, Any], q)
            choices: list[str] = [str(c) for c in cast(list[Any], q_dict.get('choices') or [])]
            correct_idx: int = int(q_dict.get('correct_index', 0))
            correct_text = choices[correct_idx] if 0 <= correct_idx < len(choices) else ''
            random.shuffle(choices)
            questions.append({
                **q_dict,
                'choices': choices,
                'correct_index': choices.index(correct_text) if correct_text in choices else 0,
            })

        if not passage:
            ext.logger.error("RC passage: empty passage in tool result")
            return jsonify({"error": "generation_failed"}), 500
    except Exception as exc:
        ext.logger.error("Reading passage generation failed: %s", exc)
        return jsonify({"error": "generation_failed"}), 500

    _last_generation[username] = time.monotonic()

    conn = sqlite3.connect(ext.DB_FILE)
    c = conn.cursor()
    c.execute(
        'INSERT OR IGNORE INTO reading_passages (passage, words_json, words_key, questions_json) '
        'VALUES (?, ?, ?, ?)',
        (
            passage,
            json.dumps(words, ensure_ascii=False),
            words_key,
            json.dumps(questions, ensure_ascii=False),
        ),
    )
    passage_id = c.lastrowid
    if passage_id:
        c.executemany(
            'INSERT INTO passage_words (passage_id, word) VALUES (?, ?)',
            [(passage_id, w.lower()) for w in words],
        )
    conn.commit()
    conn.close()

    return jsonify({"passage": passage, "questions": questions, "words": words, "cached": False})
