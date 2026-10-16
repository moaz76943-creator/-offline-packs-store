import argparse
import sys
import json
from pathlib import Path
from typing import TextIO

from tools.cefr_validation.validator import CEFRValidator

def main():
    parser = argparse.ArgumentParser(description="CEFR Evidence & Classification Validation Engine")
    parser.add_argument("--input", type=str, help="Path to input JSONL file. If absent, reads from stdin.")
    parser.add_argument("--accepted", type=str, required=True, help="Path to output accepted JSONL file.")
    parser.add_argument("--rejected", type=str, required=True, help="Path to output rejected JSONL file.")

    args = parser.parse_args()

    if args.input:
        in_stream = open(args.input, "r", encoding="utf-8")
    else:
        in_stream = sys.stdin

    validator = CEFRValidator()

    def record_generator(stream: TextIO):
        for line in stream:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)

    accepted_count = 0
    rejected_count = 0

    with open(args.accepted, "w", encoding="utf-8") as f_acc, \
         open(args.rejected, "w", encoding="utf-8") as f_rej:

        for status, record, reason in validator.validate_stream(record_generator(in_stream)):
            if status == "accepted":
                f_acc.write(json.dumps(record, ensure_ascii=False) + "\n")
                accepted_count += 1
            else:
                f_rej.write(json.dumps({"record": record, "reason": reason}, ensure_ascii=False) + "\n")
                rejected_count += 1

    if args.input:
        in_stream.close()

    print(f"Validation complete. Accepted: {accepted_count}, Rejected: {rejected_count}")

if __name__ == "__main__":
    main()
