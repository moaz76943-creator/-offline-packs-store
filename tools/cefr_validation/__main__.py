import argparse
import json
import sys
from pathlib import Path

from tools.cefr_validation.validator import CEFRValidator

def parse_args():
    parser = argparse.ArgumentParser(description="Executable evidence gate for lexical A1-C2 classifications.")
    parser.add_argument("--input", type=Path, required=True, help="Input JSONL file containing lexical records")
    parser.add_argument("--accepted", type=Path, required=True, help="Output JSONL file for accepted records")
    parser.add_argument("--rejected", type=Path, required=True, help="Output JSONL file for rejected records")
    return parser.parse_args()

def stream_records(input_path):
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            yield json.loads(line)

def main():
    args = parse_args()

    validator = CEFRValidator()

    with open(args.accepted, "w", encoding="utf-8") as f_acc, \
         open(args.rejected, "w", encoding="utf-8") as f_rej:

        for status, record, reason in validator.validate_stream(stream_records(args.input)):
            if status == "accepted":
                f_acc.write(json.dumps(record) + "\n")
            else:
                f_rej.write(json.dumps({"record": record, "reason": reason}) + "\n")

if __name__ == "__main__":
    main()
