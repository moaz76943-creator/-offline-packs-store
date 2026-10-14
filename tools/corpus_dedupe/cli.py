import sys
import json
import argparse
from tools.corpus_dedupe.engine import CorpusDeduplicator

def main():
    parser = argparse.ArgumentParser(description="Deterministic cross-source corpus deduplication engine.")
    parser.add_argument("--input", "-i", type=str, help="Input JSONL file (default: stdin)", default="-")
    parser.add_argument("--output", "-o", type=str, help="Output canonical JSONL file (default: stdout)", default="-")
    parser.add_argument("--dup-map", "-m", type=str, help="Output duplicate map JSON file")

    args = parser.parse_args()

    deduper = CorpusDeduplicator()

    def record_generator():
        if args.input == "-":
            f_in = sys.stdin
        else:
            f_in = open(args.input, 'r', encoding='utf-8')

        try:
            for line in f_in:
                line = line.strip()
                if not line:
                    continue
                yield json.loads(line)
        finally:
            if args.input != "-":
                f_in.close()

    if args.output == "-":
        f_out = sys.stdout
    else:
        f_out = open(args.output, 'w', encoding='utf-8')

    try:
        for canonical_record in deduper.process_stream(record_generator()):
            f_out.write(json.dumps(canonical_record, ensure_ascii=False) + "\n")
    finally:
        if args.output != "-":
            f_out.close()

    if args.dup_map:
        with open(args.dup_map, 'w', encoding='utf-8') as f_map:
            json.dump(deduper.get_duplicate_map(), f_map, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    main()
