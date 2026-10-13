import sys
import json
import argparse
from typing import TextIO
from .dedupe import CorpusDeduplicator

def process_stream(input_stream: TextIO, deduplicator: CorpusDeduplicator):
    for line in input_stream:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            deduplicator.process_record(record)
        except json.JSONDecodeError as e:
            print(f"Warning: Failed to parse line: {e}", file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(description="Deterministic cross-source deduplication engine")
    parser.add_argument("--input", "-i", type=str, help="Input JSONL file (default: stdin)")
    parser.add_argument("--canonical", "-c", type=str, required=True, help="Output JSONL file for canonical records")
    parser.add_argument("--duplicates", "-d", type=str, required=True, help="Output JSONL file for duplicate map")

    args = parser.parse_args()

    deduplicator = CorpusDeduplicator()

    if args.input:
        with open(args.input, 'r', encoding='utf-8') as f:
            process_stream(f, deduplicator)
    else:
        process_stream(sys.stdin, deduplicator)

    deduplicator.resolve()

    with open(args.canonical, 'w', encoding='utf-8') as f:
        for rec in deduplicator.canonical:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    with open(args.duplicates, 'w', encoding='utf-8') as f:
        for dup in deduplicator.duplicates:
            f.write(json.dumps(dup, ensure_ascii=False) + '\n')

if __name__ == "__main__":
    main()
