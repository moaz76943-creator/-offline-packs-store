import json
import re
from collections import OrderedDict

MAX_RECORD_SIZE = 1024 * 1024  # 1MB
MAX_SEEN_IDS = 100000

class LexicalQualityValidator:
    def __init__(self):
        self.seen_ids = OrderedDict()

    def validate_stream(self, stream):
        for record in stream:
            yield self.validate_record(record)

    def validate_record(self, record):
        errors = []
        reasons = []
        status = "accepted"

        try:
            record_str = json.dumps(record)
            if len(record_str.encode('utf-8')) > MAX_RECORD_SIZE:
                return {
                    "status": "rejected",
                    "record": record,
                    "errors": ["Record exceeds maximum size limit of 1MB"],
                    "reasons": []
                }
        except (TypeError, ValueError):
            return {
                "status": "rejected",
                "record": record,
                "errors": ["Record is not JSON serializable"],
                "reasons": []
            }

        # Validate ID
        record_id = record.get("id")
        if record_id is None:
            errors.append("Missing 'id' field")
        elif not isinstance(record_id, str):
            errors.append("'id' field must be a string")
        else:
            if record_id in self.seen_ids:
                errors.append(f"Duplicate ID detected: {record_id}")
            else:
                self.seen_ids[record_id] = True
                if len(self.seen_ids) > MAX_SEEN_IDS:
                    self.seen_ids.popitem(last=False)

        # Validate surface
        surface = record.get("surface")
        if surface is None:
            errors.append("Missing 'surface' field")
        elif not isinstance(surface, str):
            errors.append("'surface' field must be a string")
        elif not surface.strip():
            errors.append("'surface' field cannot be empty or whitespace")
        else:
            if '\u0000' in surface:
                errors.append("Invalid Unicode: null byte in 'surface'")
            if re.search(r'[\uD800-\uDFFF]', surface):
                errors.append("Invalid Unicode: surrogate character in 'surface'")

        # Validate language
        lang = record.get("language")
        if lang is None:
            errors.append("Missing 'language' field")
        elif not isinstance(lang, str):
            errors.append("'language' field must be a string")
        elif not re.match(r"^[a-z]{2,3}(?:-[a-zA-Z0-9-]+)*$", lang):
            errors.append("Invalid 'language' format")

        # Validate pos
        pos = record.get("pos")
        if pos is None:
            errors.append("Missing 'pos' field")
        elif not isinstance(pos, str):
            errors.append("'pos' field must be a string")

        # Validate translations
        translations = record.get("translations")
        if translations is not None:
            if not isinstance(translations, list):
                errors.append("'translations' field must be a list")
            else:
                for idx, t in enumerate(translations):
                    if not isinstance(t, dict):
                        errors.append(f"Translation at index {idx} must be a dictionary")
                    else:
                        if "language" not in t or not isinstance(t["language"], str):
                            errors.append(f"Translation at index {idx} missing or invalid 'language'")
                        if "text" not in t or not isinstance(t["text"], str):
                            errors.append(f"Translation at index {idx} missing or invalid 'text'")

        # Validate examples
        examples = record.get("examples")
        if examples is not None:
            if not isinstance(examples, list):
                errors.append("'examples' field must be a list")
            else:
                for idx, e in enumerate(examples):
                    if not isinstance(e, dict):
                        errors.append(f"Example at index {idx} must be a dictionary")
                    else:
                        if "text" not in e or not isinstance(e["text"], str):
                            errors.append(f"Example at index {idx} missing or invalid 'text'")

        # Detect impossible field combinations
        if pos == "noun" and "conjugations" in record:
            reasons.append("Impossible combination: noun with conjugations")

        if pos == "verb" and "plural" in record:
            reasons.append("Impossible combination: verb with plural")

        if errors:
            status = "rejected"
        elif reasons:
            status = "reviewRequired"

        return {
            "status": status,
            "record": record,
            "errors": errors,
            "reasons": reasons
        }
