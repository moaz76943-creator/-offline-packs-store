import argparse
import json
import sys
from pathlib import Path
from tools.cefr_validation.validator import CEFRValidator

def stream_jsonl(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)

def main():
    parser = argparse.ArgumentParser(description="CEFR Evidence & Classification Validation Gate")
    parser.add_argument("--input", required=True, type=Path, help="Input JSONL file containing classification records")
    parser.add_argument("--accepted", required=True, type=Path, help="Output JSONL file for accepted records")
    parser.add_argument("--rejected", required=True, type=Path, help="Output JSONL file for rejected records")
    args = parser.parse_args()

    validator = CEFRValidator()

    rejected_count = 0
    accepted_count = 0

    with open(args.accepted, 'w', encoding='utf-8') as acc_f, \
         open(args.rejected, 'w', encoding='utf-8') as rej_f:

        records = stream_jsonl(args.input)

        for status, rec, msg in validator.validate_stream(records):
            if status == "accepted":
                acc_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                accepted_count += 1
            else:
                out_rec = {"record": rec, "reason": msg}
                rej_f.write(json.dumps(out_rec, ensure_ascii=False) + "\n")
                rejected_count += 1

    print(f"Validation complete: {accepted_count} accepted, {rejected_count} rejected.")

    if rejected_count > 0:
        sys.exit(1)

if __name__ == '__main__':
    main()
