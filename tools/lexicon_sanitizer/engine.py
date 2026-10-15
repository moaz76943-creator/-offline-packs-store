import json
import re
from typing import Dict, Any, Tuple, Optional, Set

class SanitizerEngine:
    STATUS_ACCEPT = "ACCEPT"
    STATUS_REPAIRABLE = "REPAIRABLE"
    STATUS_QUARANTINE = "QUARANTINE"
    STATUS_REVIEW_REQUIRED = "REVIEW_REQUIRED"

    def __init__(self, registry_path: str = "catalog/language_registry.v1.json"):
        self.valid_languages: Set[str] = set()
        self.seen_identities: Set[str] = set()
        self.seen_doc_ids: Set[str] = set()
        self._load_registry(registry_path)

    def _load_registry(self, registry_path: str) -> None:
        try:
            with open(registry_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                languages = data.get("languages", {})
                if isinstance(languages, dict):
                    self.valid_languages = set(languages.keys())
                elif isinstance(languages, list):
                    # Fallback if languages is a list of objects containing 'id'
                    for lang_obj in languages:
                        if isinstance(lang_obj, dict) and "id" in lang_obj:
                            self.valid_languages.add(lang_obj["id"])
        except FileNotFoundError:
            # Stop if the public workspace is inaccessible
            raise RuntimeError(f"Required registry file {registry_path} is inaccessible. Halting execution.")

    def check_valid_unicode(self, text: str) -> bool:
        if text is None:
            return False
        if not isinstance(text, str):
            return False
        # Check for surrogate pairs or other clearly invalid unicode if needed.
        # Python handles most strings cleanly, but we can look for specific ranges
        # that are disallowed in our schema (e.g. U+D800 - U+DFFF are surrogates).
        if re.search('[\ud800-\udfff]', text):
            return False
        return True

    def _generate_identity_key(self, record: Dict[str, Any]) -> str:
        # Generate an identity key based on lexeme text, POS, language, and distinct sense/meaning.
        # The prompt requires: "Detect duplicate records using lexical and sense identity, not only normalized word spelling."
        # "Preserve distinct meanings, homographs, grammatical forms, dialects and legitimate diacritic contrasts."

        # Extract lexeme and sense data from the record
        lexemes = record.get("lexemes", [])
        senses = record.get("senses", [])

        # We will create a deterministic representation of the content
        parts = []
        for lexeme in lexemes:
            # To preserve diacritic contrasts, grammatical forms, dialects, we use the exact values
            lang = lexeme.get("language", "")
            lemma = lexeme.get("lemma", "")
            surface = lexeme.get("surface", "")
            pos = lexeme.get("pos", "")
            dialect = lexeme.get("dialect", "")
            # we need to be careful with normalization to ensure we retain the exact string
            # and don't conflate distinct unicode sequences representing the same visual character
            # if they are intended to be distinct, but we should handle basic leading/trailing spaces

            parts.append(f"L:{lang}:{pos}:{lemma}:{surface}:{dialect}")

        for sense in senses:
            concept_id = sense.get("concept_id", "")
            definition = sense.get("definition", "")
            parts.append(f"S:{concept_id}:{definition}")

        return "|".join(parts)


    def validate_and_repair(self, record: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]], str]:
        """
        Validates a single lexical record.
        Returns a tuple: (Status, Repaired_Record (if status in ACCEPT, REPAIRABLE), Reason)
        """
        if not isinstance(record, dict):
            return self.STATUS_QUARANTINE, None, "Record is not a JSON object"

        reason = ""
        status = self.STATUS_ACCEPT
        repaired_record = record.copy()
        needs_repair = False

        # 1. Structural requirements based on lexical schema
        required_keys = ["contract_version", "document_id", "lexemes", "senses", "translations", "examples", "relations"]
        missing_keys = [k for k in required_keys if k not in record]
        if missing_keys:
            return self.STATUS_QUARANTINE, None, f"Missing required keys: {missing_keys}"

        doc_id = record.get("document_id")
        if not doc_id or not isinstance(doc_id, str) or not doc_id.strip():
            return self.STATUS_QUARANTINE, None, "Empty or invalid document_id"

        if not self.check_valid_unicode(doc_id):
            return self.STATUS_QUARANTINE, None, "Invalid Unicode in document_id"

        # Strip trailing/leading spaces on document_id (repairable)
        if doc_id != doc_id.strip():
            doc_id = doc_id.strip()
            repaired_record["document_id"] = doc_id
            needs_repair = True
            reason = "Repaired leading/trailing spaces in document_id"

        if doc_id in self.seen_doc_ids:
            return self.STATUS_QUARANTINE, None, "Duplicate document_id"
        else:
            self.seen_doc_ids.add(doc_id)

        # Check languages and types
        lexemes = repaired_record.get("lexemes", [])
        if not isinstance(lexemes, list):
            return self.STATUS_QUARANTINE, None, "lexemes is not a list"

        repaired_lexemes = []
        for i, lexeme in enumerate(lexemes):
            if not isinstance(lexeme, dict):
                 return self.STATUS_QUARANTINE, None, f"lexeme at index {i} is not an object"

            lang = lexeme.get("language")
            if not lang or not isinstance(lang, str):
                return self.STATUS_QUARANTINE, None, f"lexeme at index {i} has missing or invalid language"

            # Trim language if needed
            if lang != lang.strip():
                lang = lang.strip()
                lexeme["language"] = lang
                needs_repair = True
                reason = "Repaired leading/trailing spaces in language"

            # Unsupported language
            if self.valid_languages and lang not in self.valid_languages:
                 # Check if it's mixed language or something else
                 return self.STATUS_QUARANTINE, None, f"Unsupported language code: {lang}"

            # Check for impossible field types (strict string checks for lemma, surface, pos, dialect)
            lemma = lexeme.get("lemma")
            if lemma is not None and not isinstance(lemma, str):
                 return self.STATUS_QUARANTINE, None, f"Invalid type for lemma in lexeme {i}"
            surface = lexeme.get("surface")
            if surface is not None and not isinstance(surface, str):
                 return self.STATUS_QUARANTINE, None, f"Invalid type for surface in lexeme {i}"
            pos = lexeme.get("pos")
            if pos is not None and not isinstance(pos, str):
                 return self.STATUS_QUARANTINE, None, f"Invalid type for pos in lexeme {i}"
            dialect = lexeme.get("dialect")
            if dialect is not None and not isinstance(dialect, str):
                 return self.STATUS_QUARANTINE, None, f"Invalid type for dialect in lexeme {i}"

            lemma_str = lemma or ""
            surface_str = surface or ""

            # Check lemma and surface for invalid unicode
            if not self.check_valid_unicode(lemma_str) or not self.check_valid_unicode(surface_str):
                 return self.STATUS_QUARANTINE, None, f"Invalid Unicode in lexeme {i}"

            # Strip trailing/leading whitespaces on lemma/surface (repairable)
            if isinstance(lemma_str, str) and lemma_str != lemma_str.strip():
                lexeme["lemma"] = lemma_str.strip()
                needs_repair = True
                reason = "Repaired whitespace in lemma"
            if isinstance(surface_str, str) and surface_str != surface_str.strip():
                lexeme["surface"] = surface_str.strip()
                needs_repair = True
                reason = "Repaired whitespace in surface"

            # Ensure identifiers aren't empty
            if not lexeme.get("lexeme_id"):
                return self.STATUS_QUARANTINE, None, f"Empty lexeme_id at index {i}"

            repaired_lexemes.append(lexeme)

        repaired_record["lexemes"] = repaired_lexemes

        # Check senses
        senses = repaired_record.get("senses", [])
        if not isinstance(senses, list):
            return self.STATUS_QUARANTINE, None, "senses is not a list"

        for i, sense in enumerate(senses):
            if not isinstance(sense, dict):
                 return self.STATUS_QUARANTINE, None, f"sense at index {i} is not an object"
            if not sense.get("sense_id"):
                 return self.STATUS_QUARANTINE, None, f"Empty sense_id at index {i}"

            # Check for impossible field types (strict string checks for concept_id, definition)
            concept_id = sense.get("concept_id")
            if concept_id is not None and not isinstance(concept_id, str):
                 return self.STATUS_QUARANTINE, None, f"Invalid type for concept_id in sense {i}"

            definition = sense.get("definition")
            if definition is not None and not isinstance(definition, str):
                 return self.STATUS_QUARANTINE, None, f"Invalid type for definition in sense {i}"

            if definition is not None and not self.check_valid_unicode(definition):
                 return self.STATUS_QUARANTINE, None, f"Invalid Unicode in sense {i}"

        # Translations check
        translations = repaired_record.get("translations", [])
        if not isinstance(translations, list):
            return self.STATUS_QUARANTINE, None, "translations is not a list"
        for i, t in enumerate(translations):
            if not isinstance(t, dict):
                 return self.STATUS_QUARANTINE, None, f"translation at index {i} is not an object"
            if not t.get("translation_id"):
                return self.STATUS_QUARANTINE, None, f"Empty translation_id at index {i}"

        # Duplication check
        identity_key = self._generate_identity_key(repaired_record)
        if identity_key in self.seen_identities:
            # We found a duplicate identity. Mark it for QUARANTINE or REVIEW_REQUIRED based on exact match vs near match
            # "Detect duplicate records using lexical and sense identity"
            return self.STATUS_QUARANTINE, None, "Duplicate record detected based on lexical and sense identity"
        else:
            self.seen_identities.add(identity_key)

        if needs_repair:
            status = self.STATUS_REPAIRABLE
            return status, repaired_record, reason

        return self.STATUS_ACCEPT, repaired_record, "OK"
