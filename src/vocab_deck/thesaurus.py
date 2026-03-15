"""
Merriam-Webster Thesaurus API integration.
Core functions for fetching synonyms/antonyms and matching words.
"""

import requests
import json
from typing import Dict, List, Optional
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler


LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("vocab_deck.api")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    api_handler = RotatingFileHandler(
        LOG_DIR / "api_errors.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    api_handler.setLevel(logging.ERROR)
    api_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(api_handler)


class ThesaurusAPI:
    """Interface to Merriam-Webster Collegiate Thesaurus API."""
    
    BASE_URL = "https://www.dictionaryapi.com/api/v3/references/thesaurus/json"
    
    def __init__(self, api_key: str):
        """
        Initialize the thesaurus API client.
        
        Args:
            api_key: Your Merriam-Webster API key from https://dictionaryapi.com/
        """
        self.api_key = api_key
        self.cache = {}  # Simple in-memory cache
    
    def _fetch_word_data(self, word: str) -> Optional[List[Dict]]:
        """
        Fetch raw data for a word from the API.
        
        Args:
            word: The word to lookup
            
        Returns:
            List of entry dictionaries or None if not found
        """
        # Check cache first
        if word.lower() in self.cache:
            return self.cache[word.lower()]
        
        try:
            params = {"key": self.api_key}
            response = requests.get(f"{self.BASE_URL}/{word}", params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # API returns list of strings if word not found (suggestions)
            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], str):
                return None
            
            # Cache the result
            self.cache[word.lower()] = data
            return data
            
        except requests.RequestException as e:
            logger.exception("Thesaurus API request failed for word='%s'", word)
            print(f"API request failed for '{word}': {e}")
            return None
        except Exception:
            logger.exception("Unexpected thesaurus error for word='%s'", word)
            return None
    
    def get_synonyms(self, word: str, limit: Optional[int] = None) -> List[str]:
        """
        Get synonyms for a word.
        
        Args:
            word: The word to find synonyms for
            limit: Maximum number of synonyms to return (None for all)
            
        Returns:
            List of synonym strings
        """
        data = self._fetch_word_data(word)
        if not data:
            return []
        
        synonyms = set()
        
        for entry in data:
            if isinstance(entry, dict) and "meta" in entry:
                # Get synonyms from meta.syns (list of lists)
                syns = entry.get("meta", {}).get("syns", [])
                for syn_list in syns:
                    synonyms.update(syn_list)
        
        result = sorted(list(synonyms))
        return result[:limit] if limit else result
    
    def get_antonyms(self, word: str, limit: Optional[int] = None) -> List[str]:
        """
        Get antonyms for a word.
        
        Args:
            word: The word to find antonyms for
            limit: Maximum number of antonyms to return (None for all)
            
        Returns:
            List of antonym strings
        """
        data = self._fetch_word_data(word)
        if not data:
            return []
        
        antonyms = set()
        
        for entry in data:
            if isinstance(entry, dict) and "meta" in entry:
                # Get antonyms from meta.ants (list of lists)
                ants = entry.get("meta", {}).get("ants", [])
                for ant_list in ants:
                    antonyms.update(ant_list)
        
        result = sorted(list(antonyms))
        return result[:limit] if limit else result
    
    def get_short_definition(self, word: str) -> Optional[str]:
        """
        Get a short definition/gloss for a word (first sense of first entry).

        Args:
            word: The word to define

        Returns:
            Short definition string or None
        """
        data = self._fetch_word_data(word)
        if not data or len(data) == 0:
            return None

        # Get the first shortdef if available
        if isinstance(data[0], dict):
            shortdefs = data[0].get("shortdef", [])
            if shortdefs:
                return shortdefs[0]

        return None

    def get_word_type(self, word: str) -> str:
        """
        Return the functional label (part of speech) for the primary entry.

        Returns:
            e.g. "verb", "noun", "adjective", or "" if not found
        """
        data = self._fetch_word_data(word)
        if not data:
            return ""
        for entry in data:
            if isinstance(entry, dict) and entry.get("fl"):
                return entry["fl"]
        return ""

    def get_senses(self, word: str) -> List[Dict]:
        """
        Return per-sense grouped data so that each definition is paired only
        with its own synonyms and antonyms.

        The MW Thesaurus API organises each entry (usually one per part-of-speech)
        into parallel lists:
          shortdef[i]        <- definition for sense i
          meta.syns[i]       <- synonyms for sense i
          meta.ants[i]       <- antonyms for sense i

        Returns:
            List of dicts, each with keys:
                word_type  - part of speech (e.g. "verb", "noun")
                definition - short definition for THIS sense
                synonyms   - list of synonyms for THIS sense
                antonyms   - list of antonyms for THIS sense
        """
        data = self._fetch_word_data(word)
        if not data:
            return []

        senses = []
        for entry in data:
            if not isinstance(entry, dict) or "meta" not in entry:
                continue

            fl = entry.get("fl", "")          # functional label / part of speech
            shortdefs = entry.get("shortdef", [])
            syns_lists = entry.get("meta", {}).get("syns", [])
            ants_lists = entry.get("meta", {}).get("ants", [])

            for i, defn in enumerate(shortdefs):
                senses.append({
                    "word_type": fl,
                    "definition": defn,
                    "synonyms": syns_lists[i] if i < len(syns_lists) else [],
                    "antonyms": ants_lists[i] if i < len(ants_lists) else [],
                })

        return senses
    
    def match_synonym(self, word: str, candidate: str) -> bool:
        """
        Check if a candidate word is a synonym of the target word.
        
        Args:
            word: The target word
            candidate: The word to check
            
        Returns:
            True if candidate is a synonym of word
        """
        synonyms = self.get_synonyms(word)
        return candidate.lower() in [s.lower() for s in synonyms]
    
    def match_antonym(self, word: str, candidate: str) -> bool:
        """
        Check if a candidate word is an antonym of the target word.
        
        Args:
            word: The target word
            candidate: The word to check
            
        Returns:
            True if candidate is an antonym of word
        """
        antonyms = self.get_antonyms(word)
        return candidate.lower() in [a.lower() for a in antonyms]
    
    def get_word_info(self, word: str) -> Dict:
        """
        Get complete word information including synonyms, antonyms, definition,
        part-of-speech (word_type), and per-sense grouped data (senses).

        Args:
            word: The word to lookup

        Returns:
            Dictionary with 'word', 'word_type', 'definition', 'synonyms',
            'antonyms', and 'senses' keys
        """
        senses = self.get_senses(word)
        # Derive flat lists and primary word_type from senses to stay consistent
        word_type = ""
        if senses:
            word_type = senses[0].get("word_type", "")

        return {
            "word": word,
            "word_type": word_type,
            "senses": senses,
            "synonyms": self.get_synonyms(word),
            "antonyms": self.get_antonyms(word),
            "definition": self.get_short_definition(word),
        }


def load_api_key(config_file: str = ".env") -> Optional[str]:
    """
    Load API key from config file or environment.
    
    Args:
        config_file: Path to config file with API_KEY=xxx format
        
    Returns:
        API key string or None
    """
    import os
    
    # Try environment variable first
    api_key = os.environ.get("MERRIAM_WEBSTER_API_KEY")
    if api_key:
        return api_key
    
    # Try config file
    config_path = Path(config_file)
    if config_path.exists():
        with open(config_path) as f:
            for line in f:
                if line.startswith("MERRIAM_WEBSTER_API_KEY="):
                    return line.split("=", 1)[1].strip()
    
    return None


# Example usage and testing
if __name__ == "__main__":
    # Load API key
    api_key = load_api_key()
    
    if not api_key:
        print("Error: No API key found!")
        print("Set MERRIAM_WEBSTER_API_KEY environment variable or create .env file")
        print("Get your free API key at: https://dictionaryapi.com/register/index")
        exit(1)
    
    # Initialize API
    thesaurus = ThesaurusAPI(api_key)
    
    # Test with a sample word
    test_word = "happy"
    print(f"\n=== Testing word: {test_word} ===\n")
    
    # Get synonyms
    synonyms = thesaurus.get_synonyms(test_word, limit=10)
    print(f"Synonyms ({len(synonyms)}): {', '.join(synonyms)}")
    
    # Get antonyms
    antonyms = thesaurus.get_antonyms(test_word, limit=10)
    print(f"Antonyms ({len(antonyms)}): {', '.join(antonyms)}")
    
    # Get definition
    definition = thesaurus.get_short_definition(test_word)
    print(f"Definition: {definition}")
    
    # Test matching
    print(f"\nIs 'joyful' a synonym? {thesaurus.match_synonym(test_word, 'joyful')}")
    print(f"Is 'sad' an antonym? {thesaurus.match_antonym(test_word, 'sad')}")
