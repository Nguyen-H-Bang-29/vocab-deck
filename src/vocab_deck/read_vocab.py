import argparse
import csv
import json
import re
import shutil
from pathlib import Path

import pypdf

from .data_sources import get_default_pdf_path, get_source_spec
from .thesaurus import ThesaurusAPI, load_api_key


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_ROOT = BASE_DIR / "data"
PROCESSED_DATA_DIR = DATA_ROOT / "processed"

PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)


def output_paths_for_source(source_key: str) -> tuple[Path, Path, Path]:
    """Return (words_json, words_csv, enriched_json) for a source."""
    if source_key == "vocab":
        return (
            PROCESSED_DATA_DIR / "vocab_words.json",
            PROCESSED_DATA_DIR / "vocab_words.csv",
            PROCESSED_DATA_DIR / "vocab_enriched.json",
        )
    return (
        PROCESSED_DATA_DIR / f"{source_key}_words.json",
        PROCESSED_DATA_DIR / f"{source_key}_words.csv",
        PROCESSED_DATA_DIR / f"{source_key}_enriched.json",
    )


def extract_words(pdf_path: Path, source_key: str):
    """Extract source terms from PDF (no definitions)."""
    spec = get_source_spec(source_key)
    reader = pypdf.PdfReader(pdf_path)
    seen_words = set()
    words = []

    print(f"Processing {len(reader.pages)} pages from source '{source_key}'...")

    for page_num in range(len(reader.pages)):
        text = reader.pages[page_num].extract_text() or ""
        lines = text.split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if any(line.startswith(prefix) for prefix in spec.skip_prefixes):
                continue

            match = re.match(spec.line_regex, line)
            if not match:
                continue

            candidate = re.sub(r"\s+", " ", match.group(1)).strip().lower()
            if not candidate or candidate in seen_words:
                continue

            seen_words.add(candidate)
            words.append({
                "word": candidate,
                "page": page_num + 1,
                "source": source_key,
            })

    return words


def enrich_with_thesaurus(words_list, api_key):
    """Enrich word list with synonyms, antonyms, and definitions from Merriam-Webster API."""
    thesaurus = ThesaurusAPI(api_key)
    enriched = []

    print(f"\nEnriching {len(words_list)} entries with thesaurus data...")

    for i, word_data in enumerate(words_list, 1):
        word = word_data["word"]

        if i % 50 == 0:
            print(f"  Processed {i}/{len(words_list)}...")

        info = thesaurus.get_word_info(word)

        enriched.append({
            "word": word,
            "page": word_data["page"],
            "source": word_data.get("source", "vocab"),
            "word_type": info.get("word_type", ""),
            "definition": info["definition"],
            "synonyms": info["synonyms"],
            "antonyms": info["antonyms"],
            "senses": info.get("senses", []),
            "synonym_count": len(info["synonyms"]),
            "antonym_count": len(info["antonyms"]),
        })

    print(f"  ✓ Completed enrichment for all {len(words_list)} entries")
    return enriched


def save_to_json(data, output_path: Path):
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved to {output_path.name}")


def save_to_csv(data, output_path: Path):
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["word", "page", "source"])
        writer.writeheader()
        writer.writerows(data)
    print(f"Saved to {output_path.name}")


def parse_args():
    parser = argparse.ArgumentParser(description="Warm-up extractor/enricher")
    parser.add_argument("--source", default="vocab", help="Input source key (e.g. vocab, gre_quant)")
    parser.add_argument("--pdf", default="", help="Optional custom PDF path")
    parser.add_argument(
        "--publish-web",
        action="store_true",
        help="Also copy enriched output to vocab_enriched.json for web app consumption",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    spec = get_source_spec(args.source)
    pdf_path = Path(args.pdf) if args.pdf else get_default_pdf_path(spec.key, BASE_DIR)

    if not pdf_path.exists():
        print(f"Error: PDF file not found at {pdf_path}")
        return

    words_json, words_csv, enriched_json = output_paths_for_source(spec.key)

    print(f"Reading source '{spec.key}' ({spec.label}) from {pdf_path.name}...")
    words_list = extract_words(pdf_path, spec.key)

    if not words_list:
        print("No terms found. Check PDF format and source regex in data_sources.py.")
        return

    print(f"\n✓ Extracted {len(words_list)} terms")
    save_to_json(words_list, words_json)
    save_to_csv(words_list, words_csv)

    api_key = load_api_key()
    if not api_key:
        print("\n⚠ No API key found. Skipping thesaurus enrichment.")
        print("Set MERRIAM_WEBSTER_API_KEY to enrich terms.")
        return

    enriched = enrich_with_thesaurus(words_list, api_key)
    save_to_json(enriched, enriched_json)

    if args.publish_web and enriched_json.name != "vocab_enriched.json":
        target = PROCESSED_DATA_DIR / "vocab_enriched.json"
        shutil.copyfile(enriched_json, target)
        print(f"Published {enriched_json.name} -> {target.name} for web app")

    print("\nSample enriched entries:")
    for entry in enriched[:3]:
        print(f"\n  {entry['word']} [{entry.get('word_type') or 'n/a'}]")
        print(f"    Definition: {entry['definition']}")
        print(f"    Synonyms ({entry['synonym_count']}): {', '.join(entry['synonyms'][:5]) or 'none'}")
        print(f"    Antonyms ({entry['antonym_count']}): {', '.join(entry['antonyms'][:5]) if entry['antonyms'] else 'none'}")


if __name__ == "__main__":
    main()
