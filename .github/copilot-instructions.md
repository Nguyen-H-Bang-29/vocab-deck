# Copilot Instructions for vocab-deck

## Project Overview
A Python tool for processing GregMat vocabulary PDFs and creating interactive vocabulary learning challenges. The project extracts vocabulary words from PDFs and enriches them with synonyms, antonyms, and definitions using the Merriam-Webster Thesaurus API. Core functions are designed to be exposed as web APIs for a Duolingo-style daily learning challenge.

## Tech Stack & Dependencies
- **Python 3.14+** (see `.python-version`)
- **pypdf** (6.7.4+): PDF text extraction
- **requests** (2.31.0+): HTTP client for API calls
- **uv**: Package manager (lockfile present)
- **Merriam-Webster Collegiate Thesaurus API**: Free tier (1,000 requests/day)

## Project Structure
- `read_vocab.py`: Extract words from PDF and enrich with thesaurus API
- `thesaurus.py`: Merriam-Webster API client with caching
- `quiz.py`: Challenge generation and word matching logic (future API endpoints)
- `test_api.py`: Test script for thesaurus integration
- `main.py`: Entry point (stub - TBD)
- `.env`: API key configuration (gitignored)
- `.env.example`: Template for API key setup

## Key Patterns & Conventions

### API Integration
The Merriam-Webster API requires an API key configured via:
- Environment variable: `MERRIAM_WEBSTER_API_KEY`
- `.env` file: `MERRIAM_WEBSTER_API_KEY=your_key`

Example usage pattern:
```python
from thesaurus import ThesaurusAPI, load_api_key

api_key = load_api_key()  # Loads from env or .env file
thesaurus = ThesaurusAPI(api_key)
synonyms = thesaurus.get_synonyms("happy", limit=10)
```

### Caching Strategy
`ThesaurusAPI` implements in-memory caching to minimize API calls (free tier: 1,000 req/day). Cache is per-instance, so reuse the same instance when possible.

### Core API Functions
Functions in `quiz.py` are designed as future REST API endpoints:
- `find_synonyms(word, api_key, limit)` → returns `{"status": "success", "synonyms": [...]}`
- `find_antonyms(word, api_key, limit)` → returns `{"status": "success", "antonyms": [...]}`
- `match_word_relation(word, candidate, relation, api_key)` → returns `{"is_match": True/False}`

All return consistent JSON-like dictionaries with `status` field.

### Quiz Generation
`VocabChallenge` class generates Duolingo-style challenges:
```python
challenge = VocabChallenge(enriched_words, thesaurus)
question = challenge.generate_synonym_match(difficulty="medium")
# Returns: {
#   "type": "synonym_match",
#   "word": "happy",
#   "question": "Which word is a synonym of 'happy'?",
#   "choices": ["joyful", "sad", "angry", "tired"],
#   "correct_answer": "joyful"
# }
```

## Development Workflow

### Environment Setup
```powershell
# Activate virtual environment
.venv\Scripts\Activate.ps1

# Install dependencies
uv sync

# Set API key
$env:MERRIAM_WEBSTER_API_KEY = "your-key-here"
```

### Running Scripts
```powershell
# Test API integration
uv run test_api.py

# Extract words and enrich with thesaurus data
uv run read_vocab.py

# Test thesaurus module directly
uv run thesaurus.py

# Test quiz generation
uv run quiz.py
```

## Data Flow
1. **PDF → Words**: `read_vocab.py` extracts words via regex (`^([a-z]+)` pattern)
2. **Words → Enriched**: API calls fetch synonyms/antonyms/definitions
3. **Enriched → Challenges**: `VocabChallenge` generates quiz questions
4. **Challenges → Validation**: `validate_answer()` checks user responses

## Output Files
- `vocab_words.json`: Basic word list extracted from PDF
- `vocab_words.csv`: Same data in CSV format
- `vocab_enriched.json`: Full data with synonyms/antonyms/definitions (API-enriched)

## Next Development Steps
1. **Web Interface**: HTML/JavaScript/AJAX frontend for daily challenges
2. **Database**: SQLite for user progress, streaks, scoring
3. **REST API**: Flask/FastAPI wrapper around `quiz.py` functions
4. **Authentication**: User accounts and challenge history

## API Rate Limiting
- Free tier: 1,000 API calls/day
- Cache is critical for repeated lookups
- Consider batch enrichment during off-peak hours
- Initial enrichment of 960 words = 960 API calls (use once, cache results)

## Project-Specific Notes
- GregMat PDF has 960 vocabulary words across 32 pages
- Words extracted via pattern: lowercase word at start of line
- PDF definitions are now **ignored** - using Merriam-Webster API instead
- `ThesaurusAPI` handles "word not found" gracefully (returns empty lists)
- Challenge difficulty: easy=3 choices, medium=4, hard=5

## Agent Maintenance Rule
- The leveling/personalization algorithm is defined in `README.md` under **Leveling & Personalization Algorithm (Source of Truth)**.
- Future agents must update that README section first before changing behavior in `app.py`, `quiz.py`, or frontend logic.
- Keep implementation and tests aligned with the README algorithm contract.
