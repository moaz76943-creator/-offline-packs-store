"""Source-bound CJK lexical units and bounded Unicode-safe dictionary segmentation.

No implicit character translations, readings, or proficiency classifications.
Only explicitly admitted evidence enters the segmenter.
"""
from __future__ import annotations

import hashlib
import json
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

LANGUAGES = {"zh", "ja", "ko"}
MAX_UNITS = 100_000
MAX_FORM_CHARS = 32
MAX_TEXT_CHARS = 200_000
MAX_RECORD_BYTES = 65_536
MAX_READINGS = 32
MAX_FEATURES = 32
FRAMEWORK = {"zh": "HSK", "ja": "JLPT", "ko": "TOPIK"}


def normalized(value: str) -> str:
    """Use NFC for matching; never overwrite source orthography."""
    if not isinstance(value, str) or not value or len(value) > MAX_TEXT_CHARS:
        raise ValueError("invalid or oversized Unicode text")
    if any(unicodedata.category(c) == "Cs" or c == "\x00" for c in value):
        raise ValueError("invalid Unicode scalar")
    return unicodedata.normalize("NFC", value)


def _text(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")
    normalized(value)
    return value


def validate_unit(unit: dict) -> dict:
    """Validate a single attested lexeme/sense/form. No generated evidence."""
    if not isinstance(unit, dict):
        raise ValueError("lexical unit must be an object")
    if len(json.dumps(unit, ensure_ascii=False).encode("utf-8")) > MAX_RECORD_BYTES:
        raise ValueError("lexical unit too large")
    lang = unit.get("language")
    if lang not in LANGUAGES:
        raise ValueError("unsupported CJK language")
    for field in ("unit_id", "surface", "sense_id", "source_id", "source_revision", "script", "pos"):
        _text(unit.get(field), field)
    if len(normalized(unit["surface"])) > MAX_FORM_CHARS:
        raise ValueError("surface too long")
    if unit.get("approved") is not True:
        raise ValueError("source must have explicit approved admission")
    if unit.get("level") is not None:
        level = unit["level"]
        if not isinstance(level, dict) or level.get("framework") != FRAMEWORK[lang] or not all(
            isinstance(level.get(k), str) and level[k].strip()
            for k in ("value", "source_id", "evidence_id")
        ):
            raise ValueError("framework-specific proficiency evidence required")
    readings = unit.get("readings", [])
    if not isinstance(readings, list) or len(readings) > MAX_READINGS:
        raise ValueError("invalid readings")
    seen = set()
    for reading in readings:
        if not isinstance(reading, dict):
            raise ValueError("invalid reading")
        for field in ("reading_id", "text", "system", "source_id"):
            _text(reading.get(field), field)
        if reading["reading_id"] in seen:
            raise ValueError("duplicate reading identity")
        seen.add(reading["reading_id"])
        if reading.get("language") != lang:
            raise ValueError("cross-language pronunciation prohibited")
        if reading.get("sense_id") != unit["sense_id"]:
            raise ValueError("pronunciation must be sense-scoped")
    features = unit.get("features", [])
    if not isinstance(features, list) or len(features) > MAX_FEATURES:
        raise ValueError("invalid morphology features")
    for feature in features:
        if not isinstance(feature, dict):
            raise ValueError("invalid morphology feature")
        for field in ("kind", "value", "evidence_id"):
            _text(feature.get(field), field)
    if unit.get("variants"):
        raise ValueError("implicit variants prohibited; admit each form as its own attested unit")
    return unit


@dataclass(frozen=True)
class Match:
    start: int
    end: int
    raw: str
    status: str
    units: tuple[dict, ...]


class Segmenter:
    """Greedy longest attested surface with bounded per-position work.

    Ambiguity stays visible: multiple senses on one written surface are returned
    separately, not silently resolved. Unknown symbols never become lexemes.
    """

    def __init__(self, language: str, units: Iterable[dict], max_units: int = MAX_UNITS):
        if language not in LANGUAGES:
            raise ValueError("unsupported language")
        if not 1 <= max_units <= MAX_UNITS:
            raise ValueError("invalid capacity")
        self.language = language
        self.forms: dict[str, list[dict]] = {}
        self.max_length = 0
        self.unit_count = 0
        identities = set()
        for unit in units:
            validate_unit(unit)
            if unit["language"] != language:
                raise ValueError("mixed language partition")
            identity = unit["unit_id"]
            if identity in identities:
                raise ValueError("duplicate lexical unit identity")
            identities.add(identity)
            self.unit_count += 1
            if self.unit_count > max_units:
                raise ValueError("partition exceeds capacity")
            surface = normalized(unit["surface"])
            self.forms.setdefault(surface, []).append(unit)
            self.max_length = max(self.max_length, len(surface))
        for rows in self.forms.values():
            rows.sort(key=lambda x: (x["sense_id"], x["unit_id"]))

    def segment(self, text: str) -> list[Match]:
        raw = normalized(text)
        if len(raw) > MAX_TEXT_CHARS:
            raise ValueError("text too long")
        # Preserve raw offsets: NFC can change codepoint positions. For decomposed
        # input, segments refer to normalized text and expose original separately.
        out = []
        i = 0
        while i < len(raw):
            best = None
            for size in range(min(self.max_length, len(raw) - i), 0, -1):
                candidate = raw[i:i + size]
                if candidate in self.forms:
                    best = candidate
                    break
            # A dictionary hit must not end inside a grapheme cluster. A combining
            # mark that survives NFC belongs to the preceding base, so the bare
            # surface was not the attested input.
            if best is not None and i + len(best) < len(raw) and unicodedata.combining(raw[i + len(best)]):
                best = None
            if best is not None:
                out.append(Match(i, i + len(best), best, "accepted", tuple(self.forms[best])))
                i += len(best)
            else:
                start = i
                i += 1
                # Combining marks belong to the unresolved preceding cluster.
                while i < len(raw) and unicodedata.combining(raw[i]):
                    i += 1
                out.append(Match(start, i, raw[start:i], "unmatched", ()))
        return out


def evaluate_partition(language: str, units: Iterable[dict], texts: Iterable[str]) -> dict:
    started = time.process_time()
    seg = Segmenter(language, units)
    counts = Counter()
    accepted_ids = set()
    digest = hashlib.sha256()
    for text in texts:
        normalized(text)
        digest.update(text.encode("utf-8"))
        digest.update(b"\x00")
        for match in seg.segment(text):
            counts[match.status] += 1
            for unit in match.units:
                accepted_ids.add(unit["unit_id"])
    return {
        "language": language, "dictionary_units": seg.unit_count,
        "accepted_distinct_units": len(accepted_ids),
        "accepted_segments": counts["accepted"],
        "unmatched_segments": counts["unmatched"],
        "input_sha256": digest.hexdigest(),
        "cpu_seconds": round(time.process_time() - started, 6),
        "limitations": [
            "Only approved attested surfaces are accepted",
            "Longest-match is not contextual syntactic disambiguation",
            "No automatic pronunciation or proficiency inference",
            "NFC offsets address normalized text, not original decomposed offsets",
        ],
    }
