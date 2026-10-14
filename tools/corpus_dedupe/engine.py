import json
import hashlib
import unicodedata
from collections import OrderedDict
from typing import Dict, List, Any, Generator, Tuple, Optional

def normalize_for_grouping(lemma: str) -> str:
    """Normalize lemma for grouping by lowercasing and optionally stripping some diacritics.
    We'll just lowercase and NFKC normalize.
    """
    return unicodedata.normalize('NFKC', lemma).casefold()

def get_content_hash(record: Dict[str, Any]) -> str:
    """Generate a deterministic hash of the lexical content, ignoring IDs and provenance."""
    content = {
        'language': record.get('language'),
        'lemma': record.get('lemma'),
        'pos': record.get('pos'),
        'surface': record.get('surface', record.get('lemma')),
    }

    senses = []
    for sense in record.get('senses', []):
        senses.append({
            'definition': sense.get('definition', ''),
            'concept_id': sense.get('concept_id', '')
        })
    senses.sort(key=lambda s: (s['definition'], s['concept_id']))
    content['senses'] = senses

    content_str = json.dumps(content, sort_keys=True)
    return hashlib.sha256(content_str.encode('utf-8')).hexdigest()

def get_provenance_hash(record: Dict[str, Any]) -> str:
    """Generate hash of source provenance."""
    src = record.get('source', {})
    src_content = {
        'source_id': src.get('source_id'),
        'publisher': src.get('publisher'),
        'license_id': src.get('license_id')
    }
    return hashlib.sha256(json.dumps(src_content, sort_keys=True).encode('utf-8')).hexdigest()

class CorpusDeduplicator:
    def __init__(self, max_groups: int = 10000):
        self.groups: OrderedDict[str, List[Dict[str, Any]]] = OrderedDict()
        self.duplicate_map: Dict[str, List[str]] = {}
        self.max_groups = max_groups

    def _group_key(self, lang: str, pos: str, lemma: str) -> str:
        norm_lemma = normalize_for_grouping(lemma)
        return f"{lang}|{pos}|{norm_lemma}"

    def _process_group(self, group: List[Dict[str, Any]]) -> Generator[Dict[str, Any], None, None]:
        content_groups = {}
        for rec in group:
            chash = get_content_hash(rec)
            if chash not in content_groups:
                content_groups[chash] = []
            content_groups[chash].append(rec)

        # Ensure deterministic output order by sorting content groups
        for chash in sorted(content_groups.keys()):
            subgroup = content_groups[chash]

            # Sort subgroup so that records with IDs are prioritized
            def sort_key(rec):
                rec_id = rec.get('lexeme_id') or rec.get('id') or ''
                return (0 if rec_id else 1, rec_id)
            subgroup.sort(key=sort_key)

            prov_groups = {}
            for rec in subgroup:
                phash = get_provenance_hash(rec)
                if phash not in prov_groups:
                    prov_groups[phash] = []
                prov_groups[phash].append(rec)

            canonical_records = []
            for phash in sorted(prov_groups.keys()):
                prov_group = prov_groups[phash]
                # Exact duplicates within same provenance
                canonical = prov_group[0]
                canonical_id = canonical.get('lexeme_id') or canonical.get('id')

                if canonical_id:
                    for dup in prov_group[1:]:
                        dup_id = dup.get('lexeme_id') or dup.get('id')
                        if dup_id:
                            if canonical_id not in self.duplicate_map:
                                self.duplicate_map[canonical_id] = []
                            self.duplicate_map[canonical_id].append(dup_id)

                canonical_records.append(canonical)

            if len(canonical_records) == 1:
                yield canonical_records[0]
            else:
                for rec in canonical_records:
                    rec['status'] = 'REVIEW_REQUIRED'
                    yield rec

    def process_stream(self, records_iter: Generator[Dict[str, Any], None, None]) -> Generator[Dict[str, Any], None, None]:
        """
        Process a stream of records.
        Since records must be processed completely to output them in a deterministic order
        across the whole file, we will either need a sorted input, or we must flush in LRU order
        which we did previously.
        Wait, if we flush LRU, it's deterministic based on input order.
        To fix the erratic sorting, we should just NOT sort the remaining keys, but yield them in the
        order they are in the OrderedDict (which preserves insertion/access order, which is deterministic
        based on input order).
        """
        for record in records_iter:
            lang = record.get('language', '')
            pos = record.get('pos', '')
            lemma = record.get('lemma', '')

            gkey = self._group_key(lang, pos, lemma)

            if gkey in self.groups:
                self.groups.move_to_end(gkey)
                self.groups[gkey].append(record)
            else:
                self.groups[gkey] = [record]

                if len(self.groups) > self.max_groups:
                    oldest_key, oldest_group = self.groups.popitem(last=False)
                    yield from self._process_group(oldest_group)

        # Flush the remaining groups in the order they currently exist in the OrderedDict
        # This keeps the output fully deterministic based on input order (time-ordered).
        while self.groups:
            oldest_key, oldest_group = self.groups.popitem(last=False)
            yield from self._process_group(oldest_group)

    def get_duplicate_map(self) -> Dict[str, List[str]]:
        return {k: sorted(v) for k, v in self.duplicate_map.items()}
