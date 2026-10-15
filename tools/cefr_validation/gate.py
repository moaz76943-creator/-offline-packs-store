import argparse
import sys
import json
import os
from pathlib import Path

# Fix python path issue
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.cefr_validation.validator import CEFRValidator

def main():
    parser = argparse.ArgumentParser(description="CEFR Evidence & Classification Validation Gate")
    parser.add_argument("input", type=str, help="Input JSONL file of lexical classifications")
    parser.add_argument("--accepted", type=str, required=True, help="Output file for accepted records")
    parser.add_argument("--rejected", type=str, required=True, help="Output file for rejected records")
    args = parser.parse_args()

    validator = CEFRValidator()

    def read_jsonl(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)

    records = read_jsonl(args.input)

    with open(args.accepted, 'w', encoding='utf-8') as acc_f, \
         open(args.rejected, 'w', encoding='utf-8') as rej_f:

        for status, rec, msg in validator.validate_stream(records):
            if status == "accepted":
                acc_f.write(json.dumps(rec) + "\n")
            else:
                rej_f.write(json.dumps({"record": rec, "reason": msg}) + "\n")

if __name__ == "__main__":
    main()
