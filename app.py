"""
Flask application entry point — wires shared state, registers blueprints, runs server.
"""

import json
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

load_dotenv()

import state as ext
from database import init_db, load_settings_from_db
from vocab_deck.quiz import VocabChallenge

# ── Initialize runtime singletons ────────────────────────────────────────────
from vocab_deck.thesaurus import ThesaurusAPI, load_api_key


def _load_vocab_data() -> list:
    if not ext.ENRICHED_FILE.exists():
        return []
    with open(ext.ENRICHED_FILE, encoding='utf-8') as f:
        return json.load(f)


ext.vocab_data = _load_vocab_data()

_api_key = load_api_key()
if _api_key:
    ext.thesaurus = ThesaurusAPI(_api_key)
else:
    print("WARNING: No MERRIAM_WEBSTER_API_KEY found. Some features will be limited.")

ext.challenge_gen = VocabChallenge(ext.vocab_data, ext.thesaurus) if ext.vocab_data else None

import anthropic as _anthropic_sdk

_anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
if _anthropic_api_key:
    ext.anthropic_client = _anthropic_sdk.Anthropic(api_key=_anthropic_api_key)
else:
    print("WARNING: No ANTHROPIC_API_KEY found. Reading passage generation will be unavailable.")

init_db()
ext.APP_CONFIG.update(load_settings_from_db())

# ── Flask app ─────────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder='static')
CORS(app)

from routes.challenge import challenge_bp
from routes.pages import pages_bp
from routes.passage import passage_bp
from routes.progress import progress_bp
from routes.settings import settings_bp
from routes.srs import srs_bp

for bp in [pages_bp, settings_bp, challenge_bp, progress_bp, srs_bp, passage_bp]:
    app.register_blueprint(bp)


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    ext.logger.exception("Unhandled API/server exception")
    if request.path.startswith('/api/'):
        return jsonify({"status": "error", "error": "Internal server error"}), 500
    return jsonify({"error": "Internal server error"}), 500


if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("Vocab Deck - Web Interface Starting")
    print("=" * 60)
    if not _api_key:
        print("\n  WARNING: No MERRIAM_WEBSTER_API_KEY configured.")
    if not ext.vocab_data:
        print("\n  WARNING: No enriched vocabulary data found.")
        print("  Run: uv run start.py --mode warmup --source vocab")
    else:
        print(f"\n  Loaded {len(ext.vocab_data)} vocabulary words")
    print("\n  Server starting at: http://localhost:5000")
    print("=" * 60 + "\n")
    app.run(debug=True, host='0.0.0.0', port=5000)
