"""Executable CLI for Lexical Quality Validator."""

import sys
import json
from .validator import LexicalValidator

def main():
    validator = LexicalValidator()

    # Simple JSONL streaming CLI
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            result = validator.validate_entry(entry)
            print(json.dumps(result))
        except json.JSONDecodeError as e:
            print(json.dumps({
                "status": "rejected",
                "entry": None,
                "errors": [f"Invalid JSON: {e}"],
                "warnings": []
            }))

if __name__ == '__main__':
    main()
