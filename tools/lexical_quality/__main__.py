"""Streaming CLI for multilingual lexical quality validation engine."""

import sys
import json
from .validator import LexicalValidator

def main():
    validator = LexicalValidator()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            entry = json.loads(line)
            if not isinstance(entry, dict):
                print(json.dumps({
                    "status": "rejected",
                    "entry": entry,
                    "errors": ["Entry is not a dictionary"],
                    "warnings": []
                }))
                continue
            result = validator.validate_entry(entry)
            print(json.dumps(result))
        except json.JSONDecodeError:
            print(json.dumps({
                "status": "rejected",
                "entry": None,
                "errors": ["Invalid JSON format"],
                "warnings": []
            }))

if __name__ == "__main__":
    main()
