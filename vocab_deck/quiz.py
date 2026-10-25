"""
Quiz and matching functions for vocabulary learning.
Core logic for Duolingo-style challenges.
"""

import random

from .thesaurus import ThesaurusAPI


class VocabChallenge:
    """Generate and validate vocabulary challenges."""

    def __init__(self, words_data: list[dict], thesaurus: ThesaurusAPI | None = None):
        """
        Initialize challenge generator.

        Args:
            words_data: List of word dictionaries with enriched data.
            thesaurus: Optional ThesaurusAPI instance. Not required for challenge
                       generation — synonyms/antonyms are read from pre-enriched
                       vocab_enriched.json. Only needed for live word lookups.
        """
        self.words = words_data
        self.thesaurus = thesaurus

        # Filter words that have synonyms/antonyms for challenges
        self.words_with_syns = [w for w in words_data if w.get('synonym_count', 0) > 0]
        self.words_with_ants = [w for w in words_data if w.get('antonym_count', 0) > 0]

    def _preferred_pool(self, source_pool: list[dict], preferred_words: list[str] | None) -> list[dict]:
        """Return a filtered pool that prioritizes preferred words when available."""
        if not preferred_words:
            return source_pool

        preferred_set = {word.lower() for word in preferred_words}
        filtered = [w for w in source_pool if w.get('word', '').lower() in preferred_set]
        return filtered if filtered else source_pool

    def generate_synonym_match(self, difficulty: str = "medium", preferred_words: list[str] | None = None) -> dict:
        """
        Generate a synonym matching challenge.

        Args:
            difficulty: 'easy' (3 choices), 'medium' (4), 'hard' (5)

        Returns:
            Dictionary with 'word', 'correct_answer', 'choices', 'type'
        """
        pool = self._preferred_pool(self.words_with_syns, preferred_words)

        if not pool:
            return {"error": "No words with synonyms available"}

        # Pick a random word
        word_data = random.choice(pool)
        word = word_data['word']
        synonyms = word_data['synonyms']

        if not synonyms:
            return self.generate_synonym_match(difficulty, preferred_words=preferred_words)

        # Pick correct answer
        correct = random.choice(synonyms)

        # Generate distractors (other random words or antonyms)
        num_choices = {'easy': 3, 'medium': 4, 'hard': 5}[difficulty]
        choices = [correct]

        # Add antonyms as distractors if available
        if word_data.get('antonyms'):
            choices.extend(random.sample(word_data['antonyms'],
                                        min(1, len(word_data['antonyms']))))

        # Fill remaining with random words from other vocab
        while len(choices) < num_choices:
            distractor = random.choice(self.words)['word']
            if distractor != word and distractor not in choices:
                choices.append(distractor)

        # Shuffle choices
        random.shuffle(choices)

        return {
            "type": "synonym_match",
            "word": word,
            "word_type": word_data.get('word_type', ''),
            "definition": word_data.get('definition'),
            "question": f"Which word is a synonym of '{word}'?",
            "choices": choices,
            "correct_answer": correct,
            "difficulty": difficulty
        }

    def generate_antonym_match(self, difficulty: str = "medium", preferred_words: list[str] | None = None) -> dict:
        """
        Generate an antonym matching challenge.

        Args:
            difficulty: 'easy' (3 choices), 'medium' (4), 'hard' (5)

        Returns:
            Dictionary with challenge details
        """
        pool = self._preferred_pool(self.words_with_ants, preferred_words)

        if not pool:
            return {"error": "No words with antonyms available"}

        # Pick a random word with antonyms
        word_data = random.choice(pool)
        word = word_data['word']
        antonyms = word_data['antonyms']

        if not antonyms:
            return self.generate_antonym_match(difficulty, preferred_words=preferred_words)

        # Pick correct answer
        correct = random.choice(antonyms)

        # Generate distractors
        num_choices = {'easy': 3, 'medium': 4, 'hard': 5}[difficulty]
        choices = [correct]

        # Add synonyms as distractors if available
        if word_data.get('synonyms'):
            choices.extend(random.sample(word_data['synonyms'],
                                        min(1, len(word_data['synonyms']))))

        # Fill remaining with random words
        while len(choices) < num_choices:
            distractor = random.choice(self.words)['word']
            if distractor != word and distractor not in choices:
                choices.append(distractor)

        random.shuffle(choices)

        return {
            "type": "antonym_match",
            "word": word,
            "word_type": word_data.get('word_type', ''),
            "definition": word_data.get('definition'),
            "question": f"Which word is an antonym of '{word}'?",
            "choices": choices,
            "correct_answer": correct,
            "difficulty": difficulty
        }

    def validate_answer(self, challenge: dict, user_answer: str) -> dict:
        """
        Validate a user's answer to a challenge.

        Args:
            challenge: The challenge dictionary
            user_answer: User's selected answer

        Returns:
            Dictionary with 'correct', 'correct_answer', 'explanation'
        """
        is_correct = user_answer.lower() == challenge['correct_answer'].lower()

        explanation = ""
        if is_correct:
            explanation = f"Correct! '{user_answer}' is a {challenge['type'].replace('_match', '')} of '{challenge['word']}'."
        else:
            explanation = f"Incorrect. The correct answer is '{challenge['correct_answer']}'."
            if challenge.get('definition'):
                explanation += f" {challenge['word']} means: {challenge['definition']}"

        return {
            "correct": is_correct,
            "correct_answer": challenge['correct_answer'],
            "explanation": explanation
        }

    def generate_daily_challenge(self, num_questions: int = 10, preferred_words: list[str] | None = None) -> list[dict]:
        """
        Generate a daily challenge set with mixed question types.

        Args:
            num_questions: Number of questions to generate

        Returns:
            List of challenge dictionaries
        """
        challenges = []

        for _ in range(num_questions):
            # Randomly pick synonym or antonym question
            if random.random() < 0.6:  # 60% synonyms, 40% antonyms
                challenge = self.generate_synonym_match(preferred_words=preferred_words)
            else:
                challenge = self.generate_antonym_match(preferred_words=preferred_words)

            if "error" not in challenge:
                challenges.append(challenge)

        return challenges


# API-style functions for later use

def find_synonyms(word: str, api_key: str, limit: int = 10) -> dict:
    """
    API function: Find synonyms for a word.

    Args:
        word: Target word
        api_key: Merriam-Webster API key
        limit: Maximum synonyms to return

    Returns:
        Dictionary with status and synonyms list
    """
    try:
        thesaurus = ThesaurusAPI(api_key)
        synonyms = thesaurus.get_synonyms(word, limit=limit)

        return {
            "status": "success",
            "word": word,
            "synonyms": synonyms,
            "count": len(synonyms)
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


def find_antonyms(word: str, api_key: str, limit: int = 10) -> dict:
    """
    API function: Find antonyms for a word.

    Args:
        word: Target word
        api_key: Merriam-Webster API key
        limit: Maximum antonyms to return

    Returns:
        Dictionary with status and antonyms list
    """
    try:
        thesaurus = ThesaurusAPI(api_key)
        antonyms = thesaurus.get_antonyms(word, limit=limit)

        return {
            "status": "success",
            "word": word,
            "antonyms": antonyms,
            "count": len(antonyms)
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


def match_word_relation(word: str, candidate: str, relation: str, api_key: str) -> dict:
    """
    API function: Check if candidate has a specific relation to word.

    Args:
        word: Target word
        candidate: Word to check
        relation: 'synonym' or 'antonym'
        api_key: Merriam-Webster API key

    Returns:
        Dictionary with match result
    """
    try:
        thesaurus = ThesaurusAPI(api_key)

        if relation == "synonym":
            is_match = thesaurus.match_synonym(word, candidate)
        elif relation == "antonym":
            is_match = thesaurus.match_antonym(word, candidate)
        else:
            return {
                "status": "error",
                "error": f"Invalid relation: {relation}. Use 'synonym' or 'antonym'."
            }

        return {
            "status": "success",
            "word": word,
            "candidate": candidate,
            "relation": relation,
            "is_match": is_match
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


# Example usage
if __name__ == "__main__":
    from .thesaurus import load_api_key

    api_key = load_api_key()
    if not api_key:
        print("Error: No API key found!")
        exit(1)

    # Test API functions
    print("=== Testing API Functions ===\n")

    test_word = "happy"

    # Find synonyms
    result = find_synonyms(test_word, api_key, limit=5)
    print(f"Synonyms of '{test_word}':")
    print(f"  {result}\n")

    # Find antonyms
    result = find_antonyms(test_word, api_key, limit=5)
    print(f"Antonyms of '{test_word}':")
    print(f"  {result}\n")

    # Match relation
    result = match_word_relation(test_word, "joyful", "synonym", api_key)
    print(f"Is 'joyful' a synonym of '{test_word}'?")
    print(f"  {result}\n")

    result = match_word_relation(test_word, "sad", "antonym", api_key)
    print(f"Is 'sad' an antonym of '{test_word}'?")
    print(f"  {result}\n")

    # Test challenge generation (need enriched data)
    print("=== Challenge Generation ===")
    print("(Requires enriched vocab data - run read_vocab.py first)")
