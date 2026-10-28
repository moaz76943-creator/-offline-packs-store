"""Bounded JSON Lines classifier for public lexical QA.
This executable provides a streaming validator for dictionary entries.
"""
import sys
import json
from .validator import LexicalValidator, MAX_JSON_BYTES


def main():
    with LexicalValidator() as validator:
        source = sys.stdin.buffer
        while True:
            # Bound allocation BEFORE decoding/parsing any untrusted input.
            line = source.readline(MAX_JSON_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_JSON_BYTES:
                if not line.endswith(b'\n'):
                    while True:
                        remainder = source.readline(8192)
                        if not remainder or remainder.endswith(b'\n'):
                            break
                print(json.dumps({
                    "status": "rejected", "entry": None,
                    "errors": [f"Entry exceeds size limit of {MAX_JSON_BYTES} bytes"],
                    "warnings": []
                }))
                continue
            if not line.strip():
                continue
            try:
                entry = json.loads(line.decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                print(json.dumps({
                    "status": "rejected", "entry": None,
                    "errors": [f"Invalid JSON: {exc}"], "warnings": []
                }))
                continue
            if not isinstance(entry, dict):
                print(json.dumps({
                    "status": "rejected", "entry": None,
                    "errors": ["JSON lexical entry must be an object"], "warnings": []
                }))
                continue
            print(json.dumps(validator.validate_entry(entry)))


if __name__ == "__main__":
    main()
