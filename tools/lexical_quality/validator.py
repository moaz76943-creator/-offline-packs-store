"""Multilingual Lexical Quality Validation Engine.

Detects corrupt, inconsistent, and structurally invalid dictionary records
before they enter production pack builds.
"""
import json
import re
import sys

# Constraints
MAX_JSON_BYTES = 100 * 1024  # 100 KB max per entry to strictly limit memory
LANGUAGE_REGEX = re.compile(r'^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$')
POS_ALLOWED = {"noun", "verb", "adjective", "adverb", "pronoun", "preposition", "conjunction", "interjection", "particle", "article", "affix", "phrase", "idiom", "proverb"}

class LexicalValidator:
    def __init__(self):
        self.seen_ids = set()

    def _check_string_field(self, entry, field_name, required=True):
        val = entry.get(field_name)
        if val is None:
            if required:
                return f"Missing required field '{field_name}'"
            return None
        if not isinstance(val, str):
            return f"Field '{field_name}' must be a string, got {type(val).__name__}"
        if not val.strip():
            return f"Field '{field_name}' must not be empty or whitespace only"

        # Unicode validation: look for malformed or null characters
        if '\u0000' in val:
            return f"Field '{field_name}' contains null character"
        # Check for lone surrogates (invalid Unicode)
        try:
            val.encode('utf-8')
        except UnicodeEncodeError:
            return f"Field '{field_name}' contains invalid Unicode characters"

        return None

    def validate_entry(self, entry: dict) -> dict:
        """
        Validates a single lexical entry.
        Returns:
            {"status": "accepted" | "rejected" | "reviewRequired", "entry": entry, "errors": list, "warnings": list}
        """
        errors = []
        warnings = []

        try:
            entry_bytes = json.dumps(entry).encode('utf-8')
            if len(entry_bytes) > MAX_JSON_BYTES:
                return {
                    "status": "rejected",
                    "entry": entry,
                    "errors": [f"Entry exceeds size limit of {MAX_JSON_BYTES} bytes"],
                    "warnings": []
                }
        except (TypeError, ValueError):
            return {
                "status": "rejected",
                "entry": entry,
                "errors": ["Entry is not a valid JSON serializable structure"],
                "warnings": []
            }

        # 1. Required fields: id, surface, language, pos
        id_err = self._check_string_field(entry, "id")
        if id_err:
            errors.append(id_err)
        elif entry["id"] in self.seen_ids:
            errors.append(f"Duplicate lexical ID: {entry['id']}")
        else:
            self.seen_ids.add(entry["id"])

        surf_err = self._check_string_field(entry, "surface")
        if surf_err:
            errors.append(surf_err)

        lang_err = self._check_string_field(entry, "language")
        if lang_err:
            errors.append(lang_err)
        elif not LANGUAGE_REGEX.match(entry["language"]):
            errors.append(f"Invalid language format: {entry['language']}")
        elif "id" in entry and not entry["id"].startswith(f'{entry["language"]}-'):
            # Memory constraint: language mismatch where IDs match the language prefix
            errors.append(f"ID prefix does not match language: {entry['id']} vs {entry['language']}")

        pos_err = self._check_string_field(entry, "pos")
        if pos_err:
            errors.append(pos_err)
        elif entry["pos"] not in POS_ALLOWED:
            errors.append(f"Invalid POS: {entry['pos']}")
        # We enforce strict checking of POS fields, rejecting if not in POS_ALLOWED

        # 2. Impossible field combinations
        pos = entry.get("pos")
        plural = entry.get("plural")
        conjugations = entry.get("conjugations")
        lang = entry.get("language")

        if pos and pos != "verb" and conjugations is not None:
            # While theoretically some languages decline nouns, usually 'conjugation' implies verbs.
            # We'll just mark reviewRequired instead of rejecting entirely unless we want strict rejection.
            warnings.append(f"Non-verb POS '{pos}' has 'conjugations' field")

        if pos and pos not in {"noun", "pronoun", "adjective"} and plural is not None:
            warnings.append(f"POS '{pos}' has 'plural' field, which is unusual")

        # Memory rule: grammar rules for isolating languages (zho, tha, vie)
        if lang in {"zho", "tha", "vie"}:
            if plural is not None:
                errors.append(f"Isolating language '{lang}' should not have 'plural' field")
            if conjugations is not None:
                errors.append(f"Isolating language '{lang}' should not have 'conjugations' field")

        # 3. Structure of translations
        if "translations" in entry:
            translations = entry["translations"]
            if not isinstance(translations, list):
                errors.append("Field 'translations' must be a list")
            else:
                for idx, t in enumerate(translations):
                    if not isinstance(t, dict):
                        errors.append(f"Translation at index {idx} must be a dictionary")
                        continue
                    if "language" not in t or "text" not in t:
                        errors.append(f"Translation at index {idx} missing 'language' or 'text'")
                    else:
                        lang_check = self._check_string_field(t, "language")
                        text_check = self._check_string_field(t, "text")
                        if lang_check: errors.append(f"Translation {idx}: {lang_check}")
                        if text_check: errors.append(f"Translation {idx}: {text_check}")

        # 4. Structure of examples
        if "examples" in entry:
            examples = entry["examples"]
            if not isinstance(examples, list):
                errors.append("Field 'examples' must be a list")
            else:
                for idx, ex in enumerate(examples):
                    if not isinstance(ex, dict):
                        errors.append(f"Example at index {idx} must be a dictionary")
                        continue
                    if "text" not in ex:
                        errors.append(f"Example at index {idx} missing 'text'")
                    else:
                        text_check = self._check_string_field(ex, "text")
                        if text_check: errors.append(f"Example {idx}: {text_check}")

        if errors:
            status = "rejected"
        elif warnings:
            status = "reviewRequired"
        else:
            status = "accepted"

        return {
            "status": status,
            "entry": entry,
            "errors": errors,
            "warnings": warnings
        }

    def validate_stream(self, iterator):
        """
        Generator that validates an iterator of entries.
        Yields results dictionary for each.
        """
        for entry in iterator:
            yield self.validate_entry(entry)
