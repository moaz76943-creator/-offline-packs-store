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
        except json.JSONDecodeError:
            # If line can't be decoded, skip or write an error object
            result = {
                "status": "rejected",
                "entry": None,
                "errors": ["Entry is not a valid JSON structure"],
                "warnings": []
            }
            sys.stdout.write(json.dumps(result) + '\n')
            continue

        result = validator.validate_entry(entry)
        sys.stdout.write(json.dumps(result) + '\n')

if __name__ == '__main__':
    main()
