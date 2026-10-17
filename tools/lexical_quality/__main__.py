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
        except json.JSONDecodeError as e:
            # If line is completely unparseable, we still need to classify
            print(json.dumps({
                "status": "rejected",
                "entry": None,
                "errors": [f"Invalid JSON: {str(e)}"],
                "warnings": []
            }))
            continue

        result = validator.validate_entry(entry)
        print(json.dumps(result))

if __name__ == "__main__":
    main()
