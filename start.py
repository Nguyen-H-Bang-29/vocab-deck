"""
Entry script with separated warm-up and web modes.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).parent
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"

def parse_args():
    parser = argparse.ArgumentParser(description="Vocab Deck launcher")
    parser.add_argument(
        "--mode",
        choices=["web", "warmup", "all"],
        default="web",
        help="Run only web app, only warm-up, or both",
    )
    parser.add_argument(
        "--source",
        default="vocab",
        help="Warm-up source key and web source key (e.g. vocab, gre_quant)",
    )
    parser.add_argument(
        "--pdf",
        default="",
        help="Optional custom PDF path for warm-up",
    )
    parser.add_argument(
        "--publish-web",
        action="store_true",
        help="When warm-up source is not vocab, also publish output to vocab_enriched.json",
    )
    return parser.parse_args()


def run_warmup(source: str, pdf: str = "", publish_web: bool = False):
    print("\n" + "=" * 60)
    print(f"Warm-up: source={source}")
    print("=" * 60)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    cmd = [sys.executable, "-m", "vocab_deck.read_vocab", "--source", source]
    if pdf:
        cmd.extend(["--pdf", pdf])
    if publish_web:
        cmd.append("--publish-web")

    subprocess.run(cmd, check=True, env=env)


def run_web(source: str):
    print("\n" + "=" * 60)
    print(f"Starting web server (source={source})")
    print("=" * 60 + "\n")

    env = os.environ.copy()
    env["VOCAB_DECK_SOURCE"] = source
    subprocess.run([sys.executable, "app.py"], env=env)


def main():
    args = parse_args()

    try:
        if args.mode in {"warmup", "all"}:
            run_warmup(args.source, pdf=args.pdf, publish_web=args.publish_web)

        if args.mode in {"web", "all"}:
            source_file = PROCESSED_DATA_DIR / ("vocab_enriched.json" if args.source == "vocab" else f"{args.source}_enriched.json")
            if not source_file.exists():
                print(f"\n⚠ Data file '{source_file.name}' not found for source '{args.source}'.")
                print("Run warm-up first, e.g.: uv run start.py --mode warmup --source", args.source)
                return
            run_web(args.source)
    except subprocess.CalledProcessError:
        print("\nERROR: Warm-up command failed.")
        print("Ensure API key is set if enrichment is required:")
        print("  export MERRIAM_WEBSTER_API_KEY='your-key'")
    except KeyboardInterrupt:
        print("\n\nStopped.")

if __name__ == "__main__":
    main()
