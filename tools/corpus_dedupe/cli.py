import argparse
import json
import sys
from pathlib import Path

import tempfile
from tools.corpus_dedupe.engine import CorpusDeduplicator

def main(argv=None):
    parser = argparse.ArgumentParser(description="Multilingual Corpus Sense-Aware Deduplication CLI")
    parser.add_argument("input", type=Path, help="Input JSONL stream of lexical records")
    parser.add_argument("--canonical", type=Path, default="canonical.jsonl", help="Output path for canonical records")
    parser.add_argument("--duplicates", type=Path, default="duplicates.jsonl", help="Output path for exact duplicate records")
    parser.add_argument("--review", type=Path, default="review_required.jsonl", help="Output path for records requiring review")
    args = parser.parse_args(argv)

    # Use a NamedTemporaryFile to ensure we do not hold large corpora in RAM
    temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    temp_db.close()

    deduplicator = CorpusDeduplicator(temp_db.name)

    try:
        # 1. Stream input into engine
        with open(args.input, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    deduplicator.add_record(record)
                except json.JSONDecodeError:
                    print(f"Warning: Failed to parse JSON line: {line[:50]}...", file=sys.stderr)

        # 2. Process groups and write output
        with open(args.canonical, "w", encoding="utf-8") as f_can, \
             open(args.duplicates, "w", encoding="utf-8") as f_dup, \
             open(args.review, "w", encoding="utf-8") as f_rev:

            for category, record in deduplicator.process_groups():
                line = json.dumps(record, ensure_ascii=False) + "\n"
                if category == "canonical":
                    f_can.write(line)
                elif category == "duplicate":
                    f_dup.write(line)
                elif category == "review_required":
                    f_rev.write(line)

    except OSError as e:
        print(f"Error accessing files: {e}", file=sys.stderr)
        return 1
    finally:
        deduplicator.close()
        import os
        if os.path.exists(temp_db.name):
            os.remove(temp_db.name)

    return 0

if __name__ == "__main__":
    sys.exit(main())
