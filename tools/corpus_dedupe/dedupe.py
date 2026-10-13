import hashlib
import unicodedata
import json
from collections import defaultdict
from typing import Dict, List, Any, Optional

def normalize_strict(text: str) -> str:
    if not text:
        return ""
    return unicodedata.normalize('NFKC', text).casefold()

def normalize_loose(text: str) -> str:
    if not text:
        return ""
    nfkd = unicodedata.normalize('NFKD', text).casefold()
    # Remove diacritics
    return "".join(c for c in nfkd if not unicodedata.combining(c))

class CorpusDeduplicator:
    def __init__(self):
        self.groups = defaultdict(list)
        self.canonical = []
        self.duplicates = []

    def generate_hash_key(self, record: Dict[str, Any]) -> str:
        lang = record.get('language', '')
        pos = record.get('pos', '')
        lemma = record.get('lemma', '')
        loose_lemma = normalize_loose(lemma)
        return hashlib.sha256(f"{lang}:{pos}:{loose_lemma}".encode('utf-8')).hexdigest()

    def process_record(self, record: Dict[str, Any]):
        key = self.generate_hash_key(record)
        self.groups[key].append(record)

    def is_exact_duplicate(self, rec1: Dict[str, Any], rec2: Dict[str, Any]) -> bool:
        if normalize_strict(rec1.get('lemma', '')) != normalize_strict(rec2.get('lemma', '')):
            return False

        senses1 = {normalize_strict(s.get('definition', '')) for s in rec1.get('senses', [])}
        senses2 = {normalize_strict(s.get('definition', '')) for s in rec2.get('senses', [])}

        if not senses1 and not senses2:
             return True

        if senses1 == senses2:
            return True

        return False

    def are_licenses_compatible(self, rec1: Dict[str, Any], rec2: Dict[str, Any]) -> bool:
        lic1 = rec1.get('source', {}).get('license_id', '')
        lic2 = rec2.get('source', {}).get('license_id', '')
        return lic1 == lic2

    def evaluate_group(self, group: List[Dict[str, Any]]):
        if not group:
            return

        group.sort(key=lambda x: x.get('lexeme_id', ''))

        retained = []
        for current in group:
            status = None
            duplicate_of = None
            reason = None

            for prev in retained:
                if normalize_loose(current.get('lemma', '')) == normalize_loose(prev.get('lemma', '')):
                    is_exact = self.is_exact_duplicate(current, prev)
                    lic_compat = self.are_licenses_compatible(current, prev)

                    if is_exact:
                        if lic_compat:
                            status = 'EXACT_DUPLICATE'
                            duplicate_of = prev
                            break
                        else:
                            status = 'REVIEW_REQUIRED'
                            duplicate_of = prev
                            reason = 'incompatible_licenses'
                            break
                    else:
                        # Same loose lemma, but not exact duplicate
                        strict1 = normalize_strict(current.get('lemma', ''))
                        strict2 = normalize_strict(prev.get('lemma', ''))

                        senses1 = {normalize_strict(s.get('definition', '')) for s in current.get('senses', [])}
                        senses2 = {normalize_strict(s.get('definition', '')) for s in prev.get('senses', [])}

                        if strict1 != strict2:
                            # e.g., German umlaut vs non-umlaut, Arabic diacritics
                            # Could be a near duplicate (e.g. one has diacritics, one doesn't but same meaning)
                            # If they share meaning (senses overlap), then near duplicate
                            # Otherwise, distinct word
                            if senses1 & senses2:
                                status = 'REVIEW_REQUIRED'
                                duplicate_of = prev
                                reason = 'near_duplicate_orthography'
                                break
                            else:
                                # distinct meaning, preserve
                                pass
                        else:
                            # Same strict lemma, different senses.
                            # Polysemy -> preserve both. But what if they have overlapping senses?
                            if senses1 & senses2:
                                status = 'REVIEW_REQUIRED'
                                duplicate_of = prev
                                reason = 'overlapping_senses'
                                break
                            else:
                                # disjoint senses, polysemy, preserve
                                pass

            if status == 'EXACT_DUPLICATE':
                self.duplicates.append({
                    'status': 'EXACT_DUPLICATE',
                    'original_id': current.get('lexeme_id'),
                    'duplicate_of': duplicate_of.get('lexeme_id'),
                    'source': current.get('source')
                })
            elif status == 'REVIEW_REQUIRED':
                self.duplicates.append({
                    'status': 'REVIEW_REQUIRED',
                    'original_id': current.get('lexeme_id'),
                    'duplicate_of': duplicate_of.get('lexeme_id'),
                    'source': current.get('source'),
                    'reason': reason
                })
                # We retain it since it's not an exact duplicate we can automatically merge/drop.
                # "Mark near duplicates as REVIEW_REQUIRED, not automatic deletion"
                # And "Unknown duplicates are not automatically deleted"
                retained.append(current)
            else:
                retained.append(current)

        self.canonical.extend(retained)

    def resolve(self):
        for key in sorted(self.groups.keys()):
            self.evaluate_group(self.groups[key])
        self.groups.clear()
