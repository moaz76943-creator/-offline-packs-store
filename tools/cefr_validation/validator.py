"""CEFR Validation Engine. Provides validate_stream and process_dataset."""
import copy
import json
from pathlib import Path
from typing import Iterable, Dict, Tuple, List, Generator

from tools.proficiency_mapping.engine import ProficiencyCatalog, ValidationError

CEFR_LEVELS = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}

def cefr_to_coarse(level: str) -> str:
    if level in {"A1", "A2"}:
        return "beginner"
    elif level in {"B1", "B2"}:
        return "intermediate"
    elif level in {"C1", "C2"}:
        return "advanced"
    return "unknown"


class CEFRValidator:
    def __init__(self, registry_path: Path = None):
        self.catalog = ProficiencyCatalog()
        if registry_path is None:
            registry_path = Path(__file__).resolve().parents[2] / "catalog" / "language_registry.v1.json"

        with open(registry_path, "r", encoding="utf-8") as f:
            registry_data = json.load(f)

        self.supported_languages = {
            lang["id"]: lang
            for lang in registry_data.get("languages", [])
        }
        self._history = {}

    def validate_stream(self, records: Iterable[Dict]) -> Generator[Tuple[str, Dict, str], None, None]:
        for original_record in records:
            record = copy.deepcopy(original_record)

            lexical_id = record.get("record_id")
            if not lexical_id:
                yield "rejected", original_record, "Missing lexical entry identity"
                continue

            language = record.get("language")
            if not language:
                yield "rejected", original_record, "Missing language"
                continue

            lang_code = language.split("-")[0]
            if lang_code not in self.supported_languages:
                yield "rejected", original_record, f"Unsupported language ID: {lang_code}"
                continue

            # Use Catalog to validate schema, source identity, and version bounds
            try:
                self.catalog.validate_record(record)
            except ValidationError as e:
                yield "rejected", original_record, f"Validation error: {e}"
                continue

            status = record.get("classification_status")
            framework = record.get("proficiency_framework_id")
            level = record.get("proficiency_level_id")

            # Handle unknown/unassessed explicitly
            if status in {"unknown", "unassessed"}:
                record["_resolution"] = status
                yield "accepted", record, f"Preserved {status} record"
                continue

            if framework != "CEFR":
                yield "rejected", original_record, f"Only CEFR is supported by this gate, got: {framework}"
                continue

            if level not in CEFR_LEVELS:
                yield "rejected", original_record, f"Invalid CEFR level: {level}"
                continue

            # Verify language actually has certified CEFR corpora support if source_attested
            lang_prof = self.supported_languages[lang_code].get("proficiency", {})
            if status == "source_attested" and "CEFR" not in lang_prof.get("framework_ids", []):
                yield "rejected", original_record, f"Language {lang_code} lacks certified CEFR corpora"
                continue

            # Check for conflict
            history = self._history.setdefault(lexical_id, [])
            conflict = False
            for prev_level in history:
                if abs(CEFR_LEVELS[prev_level] - CEFR_LEVELS[level]) >= 2:
                    conflict = True
                    break

            if conflict:
                record["_resolution"] = "conflicting"
                yield "rejected", original_record, "Substantial source conflict requiring review"
                continue

            history.append(level)

            record["_coarse_difficulty"] = cefr_to_coarse(level)

            if status == "source_attested":
                record["_resolution"] = "verified"
            elif status == "estimated":
                record["_resolution"] = "inferred"
            else:
                record["_resolution"] = status

            yield "accepted", record, "Valid evidence-backed classification"

    def process_dataset(self, records: Iterable[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """Consumes a stream and generates accepted and rejected output records separately."""
        accepted = []
        rejected = []
        for status, rec, msg in self.validate_stream(records):
            if status == "accepted":
                accepted.append(rec)
            else:
                # keep source datasets immutable in rejection output by just wrapping the original
                rejected.append({"record": rec, "reason": msg})
        return accepted, rejected
