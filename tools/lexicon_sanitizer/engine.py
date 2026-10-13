import json
import logging
import unicodedata
import hashlib
from typing import Dict, List, Optional, Tuple, Any, Set
from pathlib import Path
from .disk_index import DiskIndex

logger = logging.getLogger(__name__)

STATUS_ACCEPT = "ACCEPT"
STATUS_REPAIRABLE = "REPAIRABLE"
STATUS_QUARANTINE = "QUARANTINE"
STATUS_REVIEW_REQUIRED = "REVIEW_REQUIRED"

class LexiconSanitizer:
    def __init__(self, workspace_path: Optional[Path] = None):
        self._index = DiskIndex()
        self.seen_ids = self._index.set("stable_id")
        self.seen_lexeme_identities = self._index.set("lexeme_identity")
        self.seen_translation_identities = self._index.set("directed_translation_identity")
        self.seen_sense_identities = self._index.set("sense_identity")
        self._index.db.execute("CREATE TABLE lexeme_lang(id TEXT PRIMARY KEY, language TEXT NOT NULL)")
        self._index.db.execute("CREATE TABLE sense_lang(id TEXT PRIMARY KEY, language TEXT NOT NULL)")

        # Load language codes
        self.valid_languages: Set[str] = set()
        self._load_languages(workspace_path)

    def _load_languages(self, workspace_path: Optional[Path]):
        if workspace_path is None:
            workspace_path = Path(__file__).resolve().parents[2]
        registry_path = workspace_path / "catalog" / "language_registry.v1.json"
        if registry_path.exists():
            try:
                with open(registry_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for lang in data.get("languages", []):
                        self.valid_languages.add(lang.get("id"))
            except Exception as e:
                raise ValueError(f"Cannot validate against canonical language registry: {e}") from e
        if not self.valid_languages:
            raise ValueError("Missing canonical language registry: sanitizer cannot fail open")

    def close(self):
        self._index.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __del__(self):
        try:
            self.close()
        except (AttributeError, Exception):
            pass

    def check_unicode(self, text: str) -> bool:
        if not isinstance(text, str):
            return False
        for char in text:
            if unicodedata.category(char) == 'Cs':
                return False
        return True

    def repair_whitespace(self, entry: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        repaired = False
        repaired_entry = dict(entry)
        for k, v in list(repaired_entry.items()):
            if isinstance(v, str):
                stripped = v.strip()
                if stripped != v:
                    repaired_entry[k] = stripped
                    repaired = True
            elif isinstance(v, list):
                new_list = []
                for item in v:
                    if isinstance(item, str):
                        stripped = item.strip()
                        if stripped != item:
                            repaired = True
                        new_list.append(stripped)
                    else:
                        new_list.append(item)
                repaired_entry[k] = new_list
        return repaired_entry, repaired

    def compute_hash(self, entry: Dict[str, Any]) -> str:
        s = json.dumps(entry, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(s.encode('utf-8')).hexdigest()

    def sanitize_lexeme(self, entry: Dict[str, Any]) -> Tuple[str, Dict[str, Any], Optional[str]]:
        try:
            if not isinstance(entry, dict):
                return STATUS_QUARANTINE, entry, "broken JSON or not an object"

            lexeme_id = entry.get('lexeme_id')
            if not lexeme_id or not isinstance(lexeme_id, str) or not lexeme_id.strip():
                return STATUS_QUARANTINE, entry, "empty or invalid lexeme_id"

            if lexeme_id in self.seen_ids:
                return STATUS_QUARANTINE, entry, f"duplicate id {lexeme_id}"

            lang = entry.get('language')
            if not lang or not isinstance(lang, str):
                return STATUS_QUARANTINE, entry, "missing or invalid language"

            if self.valid_languages and lang not in self.valid_languages:
                return STATUS_QUARANTINE, entry, f"unsupported language code {lang}"

            lemma = entry.get('lemma')
            if not lemma or not isinstance(lemma, str):
                return STATUS_QUARANTINE, entry, "missing or invalid lemma"

            pos = entry.get('pos')
            if not pos or not isinstance(pos, str):
                return STATUS_QUARANTINE, entry, "missing or invalid pos"

            if not self.check_unicode(lemma) or not self.check_unicode(entry.get('surface', '')):
                return STATUS_QUARANTINE, entry, "invalid Unicode in fields"

            if 'pronunciations' in entry and not isinstance(entry['pronunciations'], list):
                return STATUS_QUARANTINE, entry, "impossible field type: pronunciations must be array"

            dialect = entry.get('dialect') or ''
            homograph_key = entry.get('homograph_key') or ''

            norm_lemma = unicodedata.normalize('NFC', lemma)
            identity = (lang, pos, norm_lemma, dialect, homograph_key)

            if identity in self.seen_lexeme_identities:
                # Identical surface forms may have different senses or sources.
                self.seen_ids.add(lexeme_id)
                self._index.db.execute("INSERT OR IGNORE INTO lexeme_lang VALUES(?,?)", (lexeme_id, lang))
                return STATUS_REVIEW_REQUIRED, entry, "ambiguous lexical form requires sense review"

            repaired_entry, repaired = self.repair_whitespace(entry)

            status = STATUS_REPAIRABLE if repaired else STATUS_ACCEPT
            reason = "stripped whitespace" if repaired else None

            self.seen_ids.add(lexeme_id)
            self.seen_lexeme_identities.add(identity)
            self._index.db.execute("INSERT INTO lexeme_lang VALUES(?,?)", (lexeme_id, lang))
            return status, repaired_entry, reason

        except Exception as e:
            return STATUS_QUARANTINE, entry, f"unexpected error: {str(e)}"

    def sanitize_sense(self, entry: Dict[str, Any]) -> Tuple[str, Dict[str, Any], Optional[str]]:
        try:
            if not isinstance(entry, dict):
                return STATUS_QUARANTINE, entry, "not an object"

            sense_id = entry.get('sense_id')
            if not sense_id or not isinstance(sense_id, str) or not sense_id.strip():
                return STATUS_QUARANTINE, entry, "empty or invalid sense_id"

            if sense_id in self.seen_ids:
                return STATUS_QUARANTINE, entry, f"duplicate id {sense_id}"

            concept_id = entry.get('concept_id')
            if not concept_id or not isinstance(concept_id, str):
                return STATUS_QUARANTINE, entry, "missing concept_id"

            lexeme_id = entry.get('lexeme_id')
            if not lexeme_id or not isinstance(lexeme_id, str):
                return STATUS_QUARANTINE, entry, "missing lexeme_id"

            # Check sense identity
            identity = (lexeme_id, concept_id)
            if identity in self.seen_sense_identities:
                # A shared concept need not mean an identical lexical sense.
                self.seen_ids.add(sense_id)
                return STATUS_REVIEW_REQUIRED, entry, "shared concept requires independent sense review"

            repaired_entry, repaired = self.repair_whitespace(entry)
            status = STATUS_REPAIRABLE if repaired else STATUS_ACCEPT
            reason = "stripped whitespace" if repaired else None

            self.seen_ids.add(sense_id)
            self.seen_sense_identities.add(identity)
            row = self._index.db.execute("SELECT language FROM lexeme_lang WHERE id=?", (lexeme_id,)).fetchone()
            if row:
                self._index.db.execute("INSERT INTO sense_lang VALUES(?,?)", (sense_id, row[0]))
            else:
                return STATUS_REVIEW_REQUIRED, repaired_entry, "sense lexeme identity not independently known"
            return status, repaired_entry, reason
        except Exception as e:
            return STATUS_QUARANTINE, entry, f"unexpected error: {str(e)}"

    def sanitize_translation(self, entry: Dict[str, Any]) -> Tuple[str, Dict[str, Any], Optional[str]]:
        """Stage an exact directed translation only; ambiguous provenance is reviewable.

        This sanitizer does not decide that two independently sourced records may be
        removed. The final disk-backed corpus deduplicator owns that decision.
        """
        if not isinstance(entry, dict):
            return STATUS_QUARANTINE, entry, "not an object"
        translation_id = entry.get('translation_id')
        if not isinstance(translation_id, str) or not translation_id.strip():
            return STATUS_QUARANTINE, entry, "empty or invalid translation_id"
        if translation_id in self.seen_ids:
            return STATUS_QUARANTINE, entry, f"duplicate id {translation_id}"
        text = entry.get('text')
        if not isinstance(text, str) or not text.strip() or not self.check_unicode(text):
            return STATUS_QUARANTINE, entry, "malformed translation text or invalid Unicode"
        lang = entry.get('language')
        if not isinstance(lang, str) or lang not in self.valid_languages:
            return STATUS_QUARANTINE, entry, "missing or unsupported canonical target language"
        from_sense = entry.get('from_sense_id')
        to_sense = entry.get('to_sense_id')
        if (not isinstance(from_sense, str) or not from_sense.strip()
                or not isinstance(to_sense, str) or not to_sense.strip()
                or from_sense == to_sense):
            return STATUS_QUARANTINE, entry, "invalid exact directed sense IDs"

        first = self._index.db.execute("SELECT language FROM sense_lang WHERE id=?", (from_sense,)).fetchone()
        second = self._index.db.execute("SELECT language FROM sense_lang WHERE id=?", (to_sense,)).fetchone()
        if first and second and (first[0] == second[0] or second[0] != lang):
            return STATUS_QUARANTINE, entry, "reverse/invalid directed pair identity"

        # NFC only; never erase Arabic diacritics or CJK variant distinctions.
        identity = (from_sense, to_sense, lang, unicodedata.normalize('NFC', text))
        ambiguous_identity = identity in self.seen_translation_identities
        self.seen_translation_identities.add(identity)
        repaired_entry, repaired = self.repair_whitespace(entry)
        self.seen_ids.add(translation_id)

        source = entry.get('source')
        admitted_fields = isinstance(source, dict) and all(
            isinstance(source.get(k), str) and source[k].strip()
            for k in ('source_id', 'license_id', 'dataset_version', 'record_locator'))
        if not admitted_fields:
            return STATUS_REVIEW_REQUIRED, repaired_entry, "translation source evidence missing"
        if ambiguous_identity:
            return STATUS_REVIEW_REQUIRED, repaired_entry, "translation identity overlaps another sourced record"
        if not first or not second:
            return STATUS_REVIEW_REQUIRED, repaired_entry, "directed sense language ownership unresolved"

        if lang == 'en':
            for char in text:
                if unicodedata.category(char).startswith('L'):
                    name = unicodedata.name(char, '')
                    if 'CJK' in name or 'ARABIC' in name:
                        return STATUS_REVIEW_REQUIRED, repaired_entry, "mixed-language entry suspected"

        return (STATUS_REPAIRABLE, repaired_entry, "stripped whitespace") if repaired else (STATUS_ACCEPT, repaired_entry, None)

    def sanitize_generic(self, entry: Dict[str, Any], collection: str) -> Tuple[str, Dict[str, Any], Optional[str]]:
        id_field_map = {
            'examples': 'example_id',
            'relations': 'relation_id'
        }
        id_field = id_field_map.get(collection)
        if not id_field:
            return STATUS_ACCEPT, entry, None

        try:
            entry_id = entry.get(id_field)
            if not entry_id or not isinstance(entry_id, str) or not entry_id.strip():
                return STATUS_QUARANTINE, entry, f"empty or invalid {id_field}"

            if entry_id in self.seen_ids:
                return STATUS_QUARANTINE, entry, f"duplicate id {entry_id}"

            lang = entry.get('language')
            if self.valid_languages and lang and lang not in self.valid_languages:
                return STATUS_QUARANTINE, entry, f"unsupported language code {lang}"

            repaired_entry, repaired = self.repair_whitespace(entry)
            status = STATUS_REPAIRABLE if repaired else STATUS_ACCEPT
            reason = "stripped whitespace" if repaired else None

            self.seen_ids.add(entry_id)
            return status, repaired_entry, reason
        except Exception as e:
            return STATUS_QUARANTINE, entry, f"unexpected error: {str(e)}"
