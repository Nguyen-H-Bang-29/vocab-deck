"""
Quick test script to demonstrate thesaurus API integration.
"""

from vocab_deck.quiz import find_antonyms, find_synonyms, match_word_relation
from vocab_deck.thesaurus import ThesaurusAPI, load_api_key


def main():
    print("="*60)
    print("Vocab Deck - Thesaurus API Test")
    print("="*60)

    # Load API key
    api_key = load_api_key()

    if not api_key:
        print("\n❌ No API key found!")
        print("\nTo get started:")
        print("  1. Sign up at: https://dictionaryapi.com/register/index")
        print("  2. Get your Collegiate Thesaurus API key")
        print("  3. Set environment variable:")
        print("     $env:MERRIAM_WEBSTER_API_KEY = 'your-key-here'")
        print("  4. Or create .env file with:")
        print("     MERRIAM_WEBSTER_API_KEY=your-key-here")
        return

    print("\n✓ API key loaded successfully\n")

    # Test with sample words from GregMat vocab
    test_words = ["abound", "austere", "benign"]

    print("Testing with sample GregMat vocabulary words...\n")

    for word in test_words:
        print(f"{'='*60}")
        print(f"Word: {word.upper()}")
        print(f"{'='*60}")

        # Get synonyms
        syn_result = find_synonyms(word, api_key, limit=5)
        if syn_result["status"] == "success":
            print(f"Synonyms ({syn_result['count']}): {', '.join(syn_result['synonyms'])}")

        # Get antonyms
        ant_result = find_antonyms(word, api_key, limit=5)
        if ant_result["status"] == "success":
            ants = ant_result['antonyms']
            if ants:
                print(f"Antonyms ({ant_result['count']}): {', '.join(ants)}")
            else:
                print("Antonyms: (none)")

        # Get definition
        thesaurus = ThesaurusAPI(api_key)
        definition = thesaurus.get_short_definition(word)
        if definition:
            print(f"Definition: {definition}")

        print()

    # Test matching functionality
    print(f"{'='*60}")
    print("Testing Word Matching")
    print(f"{'='*60}\n")

    # Test synonym matching
    result = match_word_relation("benign", "harmless", "synonym", api_key)
    print(f"Is 'harmless' a synonym of 'benign'? {result['is_match']}")

    result = match_word_relation("austere", "harsh", "synonym", api_key)
    print(f"Is 'harsh' a synonym of 'austere'? {result['is_match']}")

    # Test antonym matching
    result = match_word_relation("benign", "harmful", "antonym", api_key)
    print(f"Is 'harmful' an antonym of 'benign'? {result['is_match']}")

    print("\n" + "="*60)
    print("✓ All tests completed!")
    print("="*60)
    print("\nNext steps:")
    print("  1. Run: uv run read_vocab.py")
    print("     → Extract words and enrich with thesaurus data")
    print("  2. Use quiz.py functions to generate challenges")
    print("  3. Create web interface for daily learning")


if __name__ == "__main__":
    main()
