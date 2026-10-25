import sqlite3

import pytest

import app as app_module
import database
import state as ext
from vocab_deck.quiz import VocabChallenge

# ---------------------------------------------------------------------------
# Shared sample vocab large enough for real VocabChallenge distractor logic
# ---------------------------------------------------------------------------
SAMPLE_VOCAB = [
    {"word": "abound",    "definition": "be present in large numbers", "synonyms": ["teem", "overflow", "swarm"],   "antonyms": ["lack"],        "synonym_count": 3, "antonym_count": 1},
    {"word": "austere",   "definition": "stern and strict",             "synonyms": ["severe", "spartan", "stark"], "antonyms": ["luxurious"],   "synonym_count": 3, "antonym_count": 1},
    {"word": "benign",    "definition": "harmless; kindly",             "synonyms": ["harmless", "gentle"],         "antonyms": ["malignant"],   "synonym_count": 2, "antonym_count": 1},
    {"word": "capricious","definition": "having varying moods",         "synonyms": ["fickle", "erratic"],          "antonyms": ["consistent"],  "synonym_count": 2, "antonym_count": 1},
    {"word": "cerebral",  "definition": "intellectual",                 "synonyms": ["intellectual", "brainy"],     "antonyms": ["physical"],    "synonym_count": 2, "antonym_count": 1},
    {"word": "daunting",  "definition": "seeming impossible",           "synonyms": ["intimidating", "scary"],      "antonyms": ["encouraging"], "synonym_count": 2, "antonym_count": 1},
]

BASE_CONFIG = {
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


# ---------------------------------------------------------------------------
# Fixture 1: stub challenge_gen (fast, isolated)
# ---------------------------------------------------------------------------
@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test_vocab_deck.db"
    monkeypatch.setattr(ext, "DB_FILE", db_path)

    class StubChallengeGen:
        def generate_daily_challenge(self, num_questions=10, preferred_words=None):
            return [self.generate_synonym_match("medium") for _ in range(num_questions)]

        def generate_synonym_match(self, difficulty="medium", preferred_words=None):
            return {
                "type": "synonym_match",
                "word": "abound",
                "definition": "to be present in large numbers",
                "question": "Which word is a synonym of 'abound'?",
                "choices": ["teem", "lack", "quiet", "small"],
                "correct_answer": "teem",
                "difficulty": difficulty,
            }

        def generate_antonym_match(self, difficulty="medium", preferred_words=None):
            return {
                "type": "antonym_match",
                "word": "austere",
                "definition": "stern and strict",
                "question": "Which word is an antonym of 'austere'?",
                "choices": ["luxurious", "severe", "grim", "hard"],
                "correct_answer": "luxurious",
                "difficulty": difficulty,
            }

        def validate_answer(self, challenge, user_answer):
            correct = user_answer.lower() == challenge["correct_answer"].lower()
            return {
                "correct": correct,
                "correct_answer": challenge["correct_answer"],
                "explanation": "ok" if correct else "not ok",
            }

    monkeypatch.setattr(ext, "vocab_data", SAMPLE_VOCAB)
    monkeypatch.setattr(ext, "challenge_gen", StubChallengeGen())
    monkeypatch.setattr(ext, "APP_CONFIG", dict(BASE_CONFIG))

    database.init_db()
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as test_client:
        yield test_client, db_path


# ---------------------------------------------------------------------------
# Fixture 2: real VocabChallenge, no API key — mirrors production exactly
# ---------------------------------------------------------------------------
@pytest.fixture()
def real_client(tmp_path, monkeypatch):
    db_path = tmp_path / "test_vocab_deck_real.db"
    monkeypatch.setattr(ext, "DB_FILE", db_path)
    # No API key: thesaurus is None, challenge_gen built from enriched data only
    monkeypatch.setattr(ext, "vocab_data", SAMPLE_VOCAB)
    monkeypatch.setattr(ext, "challenge_gen", VocabChallenge(SAMPLE_VOCAB, thesaurus=None))
    monkeypatch.setattr(ext, "APP_CONFIG", dict(BASE_CONFIG))

    database.init_db()
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as test_client:
        yield test_client, db_path


def test_status_endpoint(client):
    test_client, _ = client
    response = test_client.get("/api/status")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["status"] == "ok"
    assert "vocab_count" in payload
    assert "config" in payload


def test_practice_page_route(client):
    test_client, _ = client
    response = test_client.get("/practice")
    assert response.status_code == 200
    assert "Practice Session" in response.get_data(as_text=True)


def test_settings_get_and_update(client):
    test_client, _ = client

    get_resp = test_client.get("/api/settings")
    assert get_resp.status_code == 200
    assert get_resp.get_json()["settings"]["practicing_limit"] == BASE_CONFIG["practicing_limit"]

    update_resp = test_client.post(
        "/api/settings",
        json={
            "practicing_limit": 90,
            "daily_questions": 12,
            "min_attempts_proficient": 3,
            "min_attempts_master": 7,
            "proficient_accuracy_threshold": 75.0,
            "master_accuracy_threshold": 90.0,
            "personalization_pool_limit": 140,
            "incorrect_carousel_size": 6,
            "incorrect_window_attempts": 80,
            "carousel_synonyms_limit": 3,
            "carousel_antonyms_limit": 2,
            "lecture_words": 4,
        },
    )
    assert update_resp.status_code == 200
    updated = update_resp.get_json()["settings"]
    assert updated["practicing_limit"] == 90
    assert updated["daily_questions"] == 12
    assert updated["incorrect_carousel_size"] == 6
    assert updated["lecture_words"] == 4


def test_projection_endpoint(client):
    test_client, _ = client
    response = test_client.get("/api/projection/tester")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["username"] == "tester"
    assert "projections" in payload
    assert len(payload["projections"]["proficient"]) == 3
    assert len(payload["projections"]["master"]) == 3


def test_incorrect_carousel_endpoint(client):
    test_client, _ = client

    challenge = {
        "type": "synonym_match",
        "word": "abound",
        "correct_answer": "teem",
    }
    test_client.post(
        "/api/validate",
        json={"challenge": challenge, "answer": "wrong", "username": "tester"},
    )

    response = test_client.get("/api/incorrect-carousel/tester")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["username"] == "tester"
    assert "cards" in payload
    assert payload["count"] >= 1
    card = payload["cards"][0]
    # Cards now expose sense-grouped data instead of flat definition/synonyms/antonyms
    assert "word" in card
    assert "senses" in card
    assert isinstance(card["senses"], list)
    assert len(card["senses"]) >= 1
    sense = card["senses"][0]
    assert "definition" in sense
    assert "synonyms" in sense
    assert "antonyms" in sense


def test_settings_invalid_thresholds(client):
    test_client, _ = client

    bad_resp = test_client.post(
        "/api/settings",
        json={
            "proficient_accuracy_threshold": 95.0,
            "master_accuracy_threshold": 90.0,
        },
    )
    assert bad_resp.status_code == 400


def test_lecture_endpoint(client):
    test_client, _ = client

    resp = test_client.get("/api/lecture/tester")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["username"] == "tester"
    assert "cards" in payload
    assert "lectured_words" in payload
    assert "session_id" in payload
    assert payload["count"] == len(payload["cards"])
    # Each card must have word + senses array
    for card in payload["cards"]:
        assert "word" in card
        assert isinstance(card["senses"], list)
        assert len(card["senses"]) >= 1
        sense = card["senses"][0]
        assert "definition" in sense
        assert "synonyms" in sense
        assert "antonyms" in sense

    # Second call reuses the same in-progress session until the challenge is answered.
    resp2 = test_client.get("/api/lecture/tester")
    assert resp2.status_code == 200
    assert resp2.get_json()["session_id"] == payload["session_id"]
    assert resp2.get_json()["lectured_words"] == payload["lectured_words"]


def test_practice_session_endpoint(client):
    test_client, _ = client

    resp = test_client.get("/api/practice-session/tester")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert "session_id" in payload
    assert "questions" in payload
    assert "lecture" in payload
    assert payload["current_index"] == 0

    session_words = []
    for question in payload["questions"]:
        if question["word"] not in session_words:
            session_words.append(question["word"])

    assert [card["word"] for card in payload["lecture"]] == session_words


def test_practice_session_resume_after_answer(client):
    test_client, db_path = client

    session = test_client.get("/api/practice-session/tester").get_json()
    first_question = session["questions"][0]

    answer_resp = test_client.post(
        f"/api/practice-session/{session['session_id']}/answer",
        json={
            "username": "tester",
            "question_index": 0,
            "answer": first_question["correct_answer"],
        },
    )
    assert answer_resp.status_code == 200
    answer_payload = answer_resp.get_json()
    assert answer_payload["already_answered"] is False
    assert answer_payload["answered_count"] == 1
    assert answer_payload["next_index"] == 1

    resumed = test_client.get("/api/practice-session/tester").get_json()
    assert resumed["session_id"] == session["session_id"]
    assert resumed["is_resumed"] is True
    assert resumed["current_index"] == 1
    assert resumed["answers"][0]["correct"] is True

    # Re-answering the same question should not duplicate history
    answer_resp_2 = test_client.post(
        f"/api/practice-session/{session['session_id']}/answer",
        json={
            "username": "tester",
            "question_index": 0,
            "answer": first_question["correct_answer"],
        },
    )
    assert answer_resp_2.status_code == 200
    assert answer_resp_2.get_json()["already_answered"] is True

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM challenge_history")
    count = cur.fetchone()[0]
    conn.close()
    assert count == 1


def test_profiles_endpoint(client):
    test_client, _ = client

    # Before any activity, profiles list should be empty (no DB rows yet)
    resp = test_client.get("/api/profiles")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert "profiles" in payload
    assert "total_vocab" in payload

    # After submitting at least one answer, the user should appear in profiles
    challenge = {
        "type": "synonym_match",
        "word": "abound",
        "correct_answer": "teem",
    }
    test_client.post(
        "/api/validate",
        json={"challenge": challenge, "answer": "teem", "username": "alice"},
    )

    resp2 = test_client.get("/api/profiles")
    assert resp2.status_code == 200
    profiles = resp2.get_json()["profiles"]
    usernames = [p["username"] for p in profiles]
    assert "alice" in usernames

    alice = next(p for p in profiles if p["username"] == "alice")
    assert "level_counts" in alice
    assert "coverage_pct" in alice
    assert set(alice["level_counts"].keys()) == {"not-learned", "practicing", "proficient", "master"}


def test_daily_challenge_endpoint(client):
    test_client, _ = client
    response = test_client.get("/api/daily-challenge?username=tester")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["username"] == "tester"
    assert payload["total"] == 10
    assert len(payload["questions"]) == 10


def test_challenge_synonym_endpoint(client):
    test_client, _ = client
    response = test_client.get("/api/challenge/synonym?difficulty=hard")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["type"] == "synonym_match"
    assert payload["difficulty"] == "hard"


def test_challenge_invalid_type(client):
    test_client, _ = client
    response = test_client.get("/api/challenge/invalid")
    assert response.status_code == 400


def test_validate_endpoint_writes_history(client):
    test_client, db_path = client

    challenge = {
        "type": "synonym_match",
        "word": "abound",
        "correct_answer": "teem",
    }
    response = test_client.post(
        "/api/validate",
        json={"challenge": challenge, "answer": "teem", "username": "tester"},
    )
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["correct"] is True

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM challenge_history")
    count = cur.fetchone()[0]
    conn.close()

    assert count == 1


def test_update_and_get_progress(client):
    test_client, _ = client

    update_resp = test_client.post(
        "/api/update-progress",
        json={"username": "tester", "score": 1, "total": 1},
    )
    assert update_resp.status_code == 200

    progress_resp = test_client.get("/api/progress/tester")
    assert progress_resp.status_code == 200

    payload = progress_resp.get_json()
    assert payload["username"] == "tester"
    assert payload["today"]["total"] >= 1


def test_random_word_endpoint(client):
    test_client, _ = client
    response = test_client.get("/api/random-word")
    assert response.status_code == 200

    payload = response.get_json()
    assert "word" in payload


def test_get_word_endpoint(client):
    test_client, _ = client

    found = test_client.get("/api/word/abound")
    assert found.status_code == 200
    assert found.get_json()["word"] == "abound"

    missing = test_client.get("/api/word/notarealword")
    assert missing.status_code == 404


def test_dashboard_endpoint(client):
    test_client, _ = client

    test_client.post(
        "/api/validate",
        json={
            "challenge": {
                "type": "synonym_match",
                "word": "abound",
                "correct_answer": "teem",
            },
            "answer": "teem",
            "username": "tester",
        },
    )

    response = test_client.get("/api/dashboard/tester")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["username"] == "tester"
    assert "latest_exercises" in payload
    assert "results" in payload
    assert "trends" in payload
    assert "streaks" in payload
    assert "word_coverage" in payload
    assert "words" in payload["word_coverage"]
    assert "level_dict" in payload
    assert "level_policy" in payload


# ---------------------------------------------------------------------------
# Real-integration tests: no API key, real VocabChallenge
# Regression guard for the "challenge_gen is None" 500 bug.
# ---------------------------------------------------------------------------

def test_daily_challenge_no_api_key(real_client):
    """
    /api/daily-challenge must return 200 without an API key configured.
    The enriched vocab file already contains synonyms/antonyms so thesaurus
    is not needed at challenge-generation time.
    """
    test_client, _ = real_client
    response = test_client.get("/api/daily-challenge?username=tester")
    assert response.status_code == 200, response.get_data(as_text=True)

    payload = response.get_json()
    assert payload["username"] == "tester"
    assert payload["total"] > 0
    q = payload["questions"][0]
    assert q["type"] in ("synonym_match", "antonym_match")
    assert q["correct_answer"] in q["choices"]


def test_challenge_synonym_no_api_key(real_client):
    test_client, _ = real_client
    response = test_client.get("/api/challenge/synonym?difficulty=medium")
    assert response.status_code == 200, response.get_data(as_text=True)

    payload = response.get_json()
    assert payload["type"] == "synonym_match"
    assert "word_type" in payload
    assert payload["correct_answer"] in payload["choices"]


def test_challenge_antonym_no_api_key(real_client):
    test_client, _ = real_client
    response = test_client.get("/api/challenge/antonym?difficulty=easy")
    assert response.status_code == 200, response.get_data(as_text=True)

    payload = response.get_json()
    assert payload["type"] == "antonym_match"
    assert payload["correct_answer"] in payload["choices"]


def test_validate_correct_answer_no_api_key(real_client):
    test_client, _ = real_client
    # First get a real question so correct_answer is valid
    q = test_client.get("/api/challenge/synonym").get_json()

    response = test_client.post(
        "/api/validate",
        json={"challenge": q, "answer": q["correct_answer"], "username": "tester"},
    )
    assert response.status_code == 200
    assert response.get_json()["correct"] is True


def test_validate_wrong_answer_no_api_key(real_client):
    test_client, _ = real_client
    q = test_client.get("/api/challenge/synonym").get_json()
    wrong = next(c for c in q["choices"] if c != q["correct_answer"])

    response = test_client.post(
        "/api/validate",
        json={"challenge": q, "answer": wrong, "username": "tester"},
    )
    assert response.status_code == 200
    assert response.get_json()["correct"] is False


def test_dashboard_no_api_key(real_client):
    test_client, _ = real_client

    q = test_client.get("/api/challenge/synonym").get_json()
    test_client.post(
        "/api/validate",
        json={"challenge": q, "answer": q["correct_answer"], "username": "tester"},
    )

    response = test_client.get("/api/dashboard/tester")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["streaks"]["current"] >= 0
    assert payload["word_coverage"]["total_vocab"] == len(SAMPLE_VOCAB)
    assert payload["word_coverage"]["words_covered"] >= 1
    first_word = next(iter(payload["level_dict"]))
    assert payload["level_dict"][first_word]["level"] in {"not-learned", "practicing", "proficient", "master"}
    assert payload["level_dict"][first_word]["color"].startswith("#")


def test_srs_easy_rating_marks_word_mastered(client):
    test_client, _ = client

    response = test_client.post(
        "/api/srs/rate",
        json={"username": "tester", "word": "abound", "quality": 5},
    )
    assert response.status_code == 200

    dashboard = test_client.get("/api/dashboard/tester").get_json()
    entry = dashboard["level_dict"]["abound"]
    assert entry["level"] == "master"
    assert entry["srs_mastered"] is True


def test_srs_easy_word_excluded_from_personalization_pool(client):
    import services

    test_client, _ = client
    test_client.post(
        "/api/srs/rate",
        json={"username": "tester", "word": "abound", "quality": 5},
    )

    level_dict = services.build_level_dictionary("tester")
    pool = services.personalization_pool(level_dict, limit=180)
    assert "abound" not in pool


def test_srs_non_easy_rating_does_not_mark_mastered(client):
    test_client, _ = client

    response = test_client.post(
        "/api/srs/rate",
        json={"username": "tester", "word": "abound", "quality": 3},
    )
    assert response.status_code == 200

    dashboard = test_client.get("/api/dashboard/tester").get_json()
    entry = dashboard["level_dict"]["abound"]
    assert entry["srs_mastered"] is False
    assert entry["level"] == "not-learned"
