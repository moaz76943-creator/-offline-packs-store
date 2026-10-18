import json
import os
import sys
import unicodedata
from pathlib import Path
from typing import Dict, Any, Optional

import jsonschema

# Documented IPA repertoire. A value is IPA only when every character is in this
# set and at least one base letter is present.
# - ASCII lowercase letters used by the IPA
# - æ ç ð ø ħ ŋ œ and Greek β θ χ
# - Latin phonetic clicks U+01C0–U+01C3
# - IPA Extensions U+0250–U+02AF
# - IPA spacing modifiers: aspiration, stress, length, rhoticity, and tone bars
# - Combining Diacritical Marks U+0300–U+036F and Supplement U+1DC0–U+1DFF
# - syllable dot and ASCII space
# Control and format characters (including newline) and symbols such as emoji
# are rejected even if a range would otherwise include them.
_IPA_REPERTOIRE = frozenset(
    "abcdefghijklmnopqrstuvwxyz ."
    "æçðøħŋœβθχ"
    + "".join(chr(code) for code in range(0x01C0, 0x01C4))
    + "".join(chr(code) for code in range(0x0250, 0x02B0))
    + "ʰʱʲʷʼˈˌːˑ˞ˠˡˤ˥˦˧˨˩"
    + "".join(chr(code) for code in range(0x0300, 0x0370))
    + "".join(chr(code) for code in range(0x1DC0, 0x1E00))
)

# An installed-voice claim has to name one vetted device, platform, and
# capability. Blanket tokens are not a scope.
_BLANKET_SCOPE = frozenset({
    "*", "all", "any", "every", "all-devices", "every-device", "guaranteed",
    "device-wide", "global", "unspecified", "unknown", "100-languages",
})

_PUBLICATION_FLAGS = "publication requires approved non-fixture pronunciation source"
_LEDGER_REJECTION = "canonical legal ledger rejected this pronunciation source"
_VOICE_SCOPE = "installed offline voice requires a device, platform, and vetted capability scope"


def _valid_ipa(value: str) -> bool:
    """Return True when value is in the documented IPA/combining-mark set."""
    if not isinstance(value, str) or not value:
        return False
    base_letter = False
    for char in value:
        # Explicit control/format/surrogate/private/unassigned rejection.
        if unicodedata.category(char)[0] == "C":
            return False
        if char not in _IPA_REPERTOIRE:
            return False
        if unicodedata.category(char)[0] == "L":
            base_letter = True
    return base_letter


def _require_voice_scope(scope: Any) -> None:
    if not isinstance(scope, dict):
        raise ValueError(_VOICE_SCOPE)
    for key in ("device", "platform", "capability"):
        value = scope.get(key)
        if (not isinstance(value, str) or not value.strip()
                or value.strip().lower() in _BLANKET_SCOPE):
            raise ValueError(_VOICE_SCOPE)


def _code_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _approved_ledger_sources(repo_root: Path) -> Dict[str, Any]:
    """Verify sources with the canonical legal-ledger evidence checks.

    A nonempty dataset_version is not publication evidence. The caller ledger
    must equal legal/ledger/sources.json and pass schema, hash, license,
    manual-review, and duplicate checks in tools/contribution_gate/evidence.py.
    """
    root = Path(repo_root).resolve()
    code_root = str(_code_root())
    if code_root not in sys.path:
        sys.path.insert(0, code_root)
    from tools.contribution_gate.evidence import verified_sources

    ledger_path = root / "legal" / "ledger" / "sources.json"
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        return verified_sources(ledger, root)
    except (OSError, ValueError) as exc:
        raise ValueError(_LEDGER_REJECTION) from exc


class PronunciationRegistry:
    def __init__(self, schema_path: Optional[str] = None, repo_root: Optional[os.PathLike] = None):
        if schema_path is None:
            schema_path = os.path.join(os.path.dirname(__file__), "pronunciation.schema.json")
        with open(schema_path, "r", encoding="utf-8") as f:
            self.schema = json.load(f)
        self.records: Dict[str, Any] = {}
        self.repo_root = Path(repo_root).resolve() if repo_root is not None else _code_root()
        self._approved: Optional[Dict[str, Any]] = None

    def _generate_key(self, record: Dict[str, Any]) -> str:
        """Stable identity including locale and other variant fields.

        Language, lexeme, sense, script, locale, dialect, notation, and value
        all distinguish a pronunciation. en-US and en-GB therefore do not
        overwrite each other when dialect is absent.
        """
        parts = [
            record["language"],
            record["lexeme_id"],
            record.get("sense_id") or "",
            record["script"],
            record["locale"],
            record.get("dialect") or "",
            record["notation"],
            record["value"],
        ]
        return "|".join(parts)

    def _validate_schema(self, record: Dict[str, Any]) -> None:
        try:
            inner_schema = self.schema["$defs"]["pronunciation_record"]
            resolver = jsonschema.validators.RefResolver.from_schema(self.schema)
            inner_validator = jsonschema.Draft202012Validator(
                inner_schema, resolver=resolver, format_checker=jsonschema.FormatChecker()
            )
            inner_validator.validate(record)
        except jsonschema.ValidationError as e:
            raise ValueError(f"Invalid record: {e.message}")

    def _ledger_sources(self) -> Dict[str, Any]:
        if self._approved is None:
            self._approved = _approved_ledger_sources(self.repo_root)
        return self._approved

    def _require_publication(self, record: Dict[str, Any]) -> None:
        """Apply the lexical pronunciation publication rule and the legal ledger.

        standards/lexical/validate.py admits a pronunciation for publication
        only when its source is publication-approved. fixture_only sources are
        rejected the same way as other publication evidence. Licenses are never
        inferred here; the canonical ledger has to already contain the source.
        """
        source = record.get("source")
        if (not isinstance(source, dict)
                or source.get("publication_approved") is not True
                or source.get("fixture_only") is not False):
            raise ValueError(_PUBLICATION_FLAGS)
        approved = self._ledger_sources()
        src = approved.get(source.get("source_id"))
        if (not isinstance(src, dict)
                or src.get("kind") != "pronunciation"
                or src.get("status") != "APPROVED_FOR_REDISTRIBUTION"
                or source.get("dataset_version") != src.get("dataset_version")):
            raise ValueError(_LEDGER_REJECTION)

    def add_record(self, record: Dict[str, Any]):
        """Validates and adds a pronunciation record to the registry."""
        self._validate_schema(record)

        if record.get("source", {}).get("source_id") == "auto-gen-orthography":
            raise ValueError("Auto-generating pronunciation from orthographic spelling is not allowed")

        if record.get("notation") == "ipa" and not _valid_ipa(record.get("value", "")):
            raise ValueError("Invalid Unicode IPA symbols detected")

        if record.get("offline_voice_support") == "installed":
            _require_voice_scope(record.get("offline_voice_scope"))

        self._require_publication(record)

        key = self._generate_key(record)
        self.records[key] = record

    def compile(self, document_id: str) -> Dict[str, Any]:
        """Compiles the registry into a deterministic JSON object matching the full schema."""
        sorted_records = [self.records[k] for k in sorted(self.records.keys())]

        doc = {
            "contract_version": "1.0.0",
            "document_id": document_id,
            "pronunciations": sorted_records
        }
        jsonschema.validate(instance=doc, schema=self.schema)
        return doc

    def export_json(self, document_id: str, filepath: str):
        """Exports the compiled registry to a JSON file."""
        doc = self.compile(document_id)
        if len(self.records) > 100000:
            raise ValueError("Input size exceeded bounded limit")

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
