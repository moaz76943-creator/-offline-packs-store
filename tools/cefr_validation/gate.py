import argparse
import sys
import json
from pathlib import Path
from tools.cefr_validation.validator import CEFRValidator

def main():
    parser = argparse.ArgumentParser(description="CEFR Classification Evidence Gate")
    parser.add_argument("--input", type=Path, required=True, help="Input JSONL file")
    parser.add_argument("--accepted", type=Path, required=True, help="Output JSONL file for accepted records")
    parser.add_argument("--rejected", type=Path, required=True, help="Output JSONL file for rejected records")
    args = parser.parse_args()

    validator = CEFRValidator()

    def stream_records(path):
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)

    with open(args.accepted, 'w', encoding='utf-8') as f_acc, \
         open(args.rejected, 'w', encoding='utf-8') as f_rej:
        for status, record, reason in validator.validate_stream(stream_records(args.input)):
            if status == "accepted":
                f_acc.write(json.dumps(record, ensure_ascii=False) + '\n')
            else:
                f_rej.write(json.dumps({"record": record, "reason": reason}, ensure_ascii=False) + '\n')

if __name__ == "__main__":
    main()
