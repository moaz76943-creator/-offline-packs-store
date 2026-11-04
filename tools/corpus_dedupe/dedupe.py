"""Fail-closed, disk-backed, sense-aware lexical duplicate analysis.

No attestation or license inference: absence of evidence never authorizes removal.
Results are streamed from SQLite; legacy resolve() is deliberately size limited.
"""
import hashlib
import json
import sqlite3
import tempfile
import unicodedata
from pathlib import Path


def normalize_strict(text):
    """Candidate comparison, never authorization for exact lexical equality."""
    return unicodedata.normalize('NFKC', text).casefold()


def normalize_loose(text):
    """Candidate *review* grouping only; never an exact-identity equality."""
    decomposed = unicodedata.normalize('NFKD', text).casefold()
    return ''.join(ch for ch in decomposed if not unicodedata.combining(ch))


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _text(value):
    return value if isinstance(value, str) and value.strip() else ''


def _rights(source):
    if not isinstance(source, dict):
        return None
    required = ('source_id', 'license_id', 'dataset_version', 'record_locator')
    if not all(_text(source.get(key)) for key in required):
        return None
    if source.get('publication_approved') is not True or source.get('fixture_only') is not False:
        return None
    return source['license_id']


def _sense_tokens(senses):
    if not isinstance(senses, list):
        raise ValueError('senses must be a list')
    result = []
    for sense in senses:
        if not isinstance(sense, dict):
            raise ValueError('sense must be an object')
        definition = _text(sense.get('definition'))
        if definition:
            result.append(_digest(normalize_strict(definition)))
    return tuple(sorted(set(result)))


def _exact_identity(rec):
    senses = rec.get('senses', [])
    # Without independently pinned concept identity and definition, no automatic removal.
    if not senses or not all(isinstance(s, dict) and _text(s.get('concept_id'))
                              and _text(s.get('definition')) and isinstance(s.get('source'), dict)
                              for s in senses):
        return None
    if not _rights(rec.get('source')):
        return None
    if not all(_rights(s['source']) == _rights(rec['source'])
               for s in senses):
        return None
    facets = {k: v for k, v in rec.items() if k not in ('source', 'senses', 'lexeme_id')}
    # A lexical sense ID is not interchangeable with a concept ID.
    sense_facets = [{k: v for k, v in s.items()
                     if k not in ('sense_id', 'lexeme_id', 'source')}
                    for s in senses]
    return _digest([facets, sorted(_json(x) for x in sense_facets)])


class CorpusDeduplicator:
    def __init__(self, *, max_record_bytes=2_000_000, legacy_result_limit=10_000,
                 admitted_source_licenses=None):
        self._temp = tempfile.TemporaryDirectory(prefix='corpus-dedupe-')
        self._db = sqlite3.connect(str(Path(self._temp.name) / 'dedupe.sqlite3'))
        self._db.execute('PRAGMA cache_size=-4096')
        self._db.execute('PRAGMA temp_store=FILE')
        self._db.executescript("""
            CREATE TABLE input (seq INTEGER PRIMARY KEY, bucket TEXT NOT NULL,
              lexeme_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL);
            CREATE INDEX input_order ON input(bucket,lexeme_id,seq);
            CREATE TABLE retained (id INTEGER PRIMARY KEY, bucket TEXT NOT NULL,
              lexeme_id TEXT NOT NULL, exact_key TEXT, strict_lemma TEXT NOT NULL,
              license TEXT, rights_ok INTEGER NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX retained_exact ON retained(bucket,strict_lemma,exact_key);
            CREATE TABLE retained_senses (bucket TEXT NOT NULL, token TEXT NOT NULL,
              retained_id INTEGER NOT NULL);
            CREATE INDEX retained_senses_lookup ON retained_senses(bucket,token);
        """)
        if admitted_source_licenses is None:
            # Read the real, independent Route-05 ledger; never trust row-level flags alone.
            path = Path(__file__).resolve().parents[2] / 'legal' / 'ledger' / 'sources.json'
            ledger = json.loads(path.read_text(encoding='utf-8'))
            admitted_source_licenses = {
                item['source_id']: (item['license']['id'], item['dataset_version'])
                for item in ledger['sources']
                if item.get('status') == 'APPROVED_FOR_REDISTRIBUTION'
                and isinstance(item.get('review'), dict)
                and item['review'].get('reviewer')
                and item['review'].get('decision_url')
            }
        self.admitted_source_licenses = dict(admitted_source_licenses)
        self.max_record_bytes = max_record_bytes
        self.legacy_result_limit = legacy_result_limit
        self.canonical = []
        self.duplicates = []
        self._resolved = False

    def close(self):
        if self._db is not None:
            self._db.close()
            self._db = None
            self._temp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def process_record(self, record):
        if self._resolved:
            raise ValueError('cannot add after resolution')
        if not isinstance(record, dict):
            raise ValueError('record must be an object')
        required = ('language', 'pos', 'lemma', 'lexeme_id')
        if not all(_text(record.get(field)) for field in required):
            raise ValueError('missing language/pos/lemma/lexeme_id')
        # No unpaired surrogate or silent Unicode rewrite.
        payload = _json(record)
        if len(payload.encode('utf-8')) > self.max_record_bytes:
            raise ValueError('oversized input record')
        _sense_tokens(record.get('senses', []))
        bucket = _digest([record['language'], record.get('script'), record['pos'],
                          record.get('dialect'), record.get('homograph_key'),
                          normalize_loose(record['lemma'])])
        try:
            self._db.execute('INSERT INTO input(bucket,lexeme_id,payload) VALUES(?,?,?)',
                             (bucket, record['lexeme_id'], payload))
        except sqlite3.IntegrityError as exc:
            raise ValueError('duplicate lexeme_id: ' + record['lexeme_id']) from exc

    def generate_hash_key(self, record):
        return _digest([record.get('language'), record.get('script'), record.get('pos'),
                        record.get('dialect'), record.get('homograph_key'),
                        normalize_loose(record.get('lemma', ''))])

    def are_licenses_compatible(self, rec1, rec2):
        license1 = _rights(rec1.get('source'))
        license2 = _rights(rec2.get('source'))
        src1 = rec1.get('source') or {}
        src2 = rec2.get('source') or {}
        return (license1 is not None and license1 == license2
                and self.admitted_source_licenses.get(src1.get('source_id')) ==
                    (license1, src1.get('dataset_version'))
                and self.admitted_source_licenses.get(src2.get('source_id')) ==
                    (license2, src2.get('dataset_version')))

    def _all_sources_admitted(self, rec):
        source = rec.get('source') or {}
        senses = rec.get('senses') or []
        if not isinstance(senses, list) or not senses:
            return False
        return all(
            isinstance(item, dict) and _rights(item.get('source'))
            and self.admitted_source_licenses.get(item['source']['source_id']) ==
                (item['source']['license_id'], item['source']['dataset_version'])
            for item in [rec, *senses]
        )

    def is_exact_duplicate(self, rec1, rec2):
        one, two = _exact_identity(rec1), _exact_identity(rec2)
        return (one is not None and one == two and self.are_licenses_compatible(rec1, rec2)
                and self._all_sources_admitted(rec1) and self._all_sources_admitted(rec2))

    def iter_resolved(self):
        if self._resolved:
            raise ValueError('resolution is single-use')
        self._resolved = True
        self._db.commit()
        for bucket, _rid, payload in self._db.execute(
                'SELECT bucket,lexeme_id,payload FROM input ORDER BY bucket,lexeme_id,seq'):
            rec = json.loads(payload)
            strict = normalize_strict(rec['lemma'])
            exact = _exact_identity(rec) if self._all_sources_admitted(rec) else None
            license_id = _rights(rec.get('source'))
            canonical = None
            reason = None
            if exact is not None:
                canonical = self._db.execute("""SELECT lexeme_id,payload FROM retained
                    WHERE bucket=? AND strict_lemma=? AND exact_key=? ORDER BY id LIMIT 1""",
                    (bucket, strict, exact)).fetchone()
            # Missing rights or semantics must never cause an automatic delete.
            if canonical:
                if self.are_licenses_compatible(rec, json.loads(canonical[1])):
                    yield 'duplicate', {'status': 'EXACT_DUPLICATE',
                        'original_id': rec['lexeme_id'], 'duplicate_of': canonical[0],
                        'source': rec.get('source'),
                        'canonical_source': json.loads(canonical[1]).get('source'),
                        'original_record': rec}
                    continue
                reason = 'incompatible_licenses'
            if reason is None:
                other = self._db.execute("""SELECT lexeme_id,payload,license,exact_key
                    FROM retained WHERE bucket=? AND strict_lemma=? ORDER BY id LIMIT 1""",
                    (bucket,strict)).fetchone()
                if other:
                    old = json.loads(other[1])
                    same_semantics = _sense_tokens(rec.get('senses', [])) == _sense_tokens(old.get('senses', []))
                    if same_semantics:
                        first = (rec.get('source') or {}).get('license_id')
                        second = (old.get('source') or {}).get('license_id')
                        reason = ('incompatible_licenses' if first and second and first != second
                                  else 'missing_or_unapproved_source' if not self.are_licenses_compatible(rec, old)
                                  else 'unverified_sense_identity')
                        canonical = other
            if reason is None:
                for token in _sense_tokens(rec.get('senses', [])):
                    near = self._db.execute("""SELECT r.lexeme_id,r.payload,r.exact_key FROM retained_senses s
                        LEFT JOIN retained r ON r.id=s.retained_id WHERE s.bucket=? AND s.token=? ORDER BY r.id LIMIT 1""",
                        (bucket,token)).fetchone()
                    if near:
                        canonical = near
                        old = json.loads(near[1])
                        reason = ('overlapping_senses' if strict == normalize_strict(old['lemma'])
                                  else 'near_duplicate_orthography')
                        break
            if reason:
                yield 'duplicate', {'status': 'REVIEW_REQUIRED',
                    'original_id': rec['lexeme_id'], 'duplicate_of': canonical[0],
                    'source': rec.get('source'), 'reason': reason}
            # Retain all records needing review (no destructive deduplication).
            cur = self._db.execute("""INSERT INTO retained(bucket,lexeme_id,exact_key,strict_lemma,
                license,rights_ok,payload) VALUES(?,?,?,?,?,?,?)""",
                (bucket,rec['lexeme_id'],exact,strict,license_id,int(license_id is not None),payload))
            self._db.executemany('INSERT INTO retained_senses VALUES(?,?,?)',
                                 ((bucket, token, cur.lastrowid) for token in _sense_tokens(rec.get('senses', []))))
            yield 'canonical', rec
        self._db.commit()

    def resolve(self):
        count = self._db.execute('SELECT COUNT(*) FROM input').fetchone()[0]
        if count > self.legacy_result_limit:
            raise ValueError('legacy in-memory resolve limit exceeded; use iter_resolved()')
        for kind, value in self.iter_resolved():
            (self.canonical if kind == 'canonical' else self.duplicates).append(value)
