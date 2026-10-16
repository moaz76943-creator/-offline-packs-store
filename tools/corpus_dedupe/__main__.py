import argparse
import json
import os
import sys

from tools.corpus_dedupe.engine import CorpusDeduplicator

def main():
    parser = argparse.ArgumentParser(description="Multilingual Corpus Deduplication Engine")
    parser.add_argument("--input", required=True, help="Input JSONL file")
    parser.add_argument("--output-dir", required=True, help="Output directory for processed files")
    parser.add_argument("--db-path", default=":memory:", help="SQLite database path (default in-memory)")

    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    canonical_path = os.path.join(args.output_dir, "canonical.jsonl")
    duplicate_path = os.path.join(args.output_dir, "duplicates.jsonl")
    review_path = os.path.join(args.output_dir, "review_required.jsonl")

    deduper = CorpusDeduplicator(db_path=args.db_path)

    # Phase 1: Ingestion
    with open(args.input, "r", encoding="utf-8") as in_f:
        for line in in_f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                deduper.ingest_record(record)
            except json.JSONDecodeError:
                print(f"Warning: Failed to parse JSON line: {line[:50]}...", file=sys.stderr)

    # Phase 2: Processing and output
    with open(canonical_path, "w", encoding="utf-8") as can_f, \
         open(duplicate_path, "w", encoding="utf-8") as dup_f, \
         open(review_path, "w", encoding="utf-8") as rev_f:

        for status, record, dup_info in deduper.process_groups():
            if dup_info:
                # Inject duplicate metadata non-destructively
                record["_dedupe_metadata"] = dup_info

            line_out = json.dumps(record, ensure_ascii=False) + "\n"

            if status == "CANONICAL":
                can_f.write(line_out)
            elif status == "DUPLICATE":
                dup_f.write(line_out)
            elif status == "REVIEW_REQUIRED":
                rev_f.write(line_out)

    deduper.close()
    print("Deduplication completed successfully.")

if __name__ == "__main__":
    main()
