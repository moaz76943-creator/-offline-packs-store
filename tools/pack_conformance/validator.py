"""Conformance for the existing reference SQLite v2 projection.

Structural validity and canonical source evidence are separate results. This
adapter never approves publication and never modifies the inspected database.
"""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

from jsonschema import Draft202012Validator
from standards.lexical.sqlite_v2 import DDL, MAPPING_VERSION, SQLITE_USER_VERSION, sort_key
from tools.contribution_gate.evidence import load_verified_ledger
from tools.gha_factory.pack_conformance.check import strict_json
from tools.pack_manifest.builder import compute_sha256

ROOT = Path(__file__).resolve().parents[2]
MAX_DATABASE = 80 * 1024 * 1024
MAX_JSON = 2_000_000


class PackConformanceError(ValueError):
    pass


def object_json(raw):
    try:
        obj = strict_json(raw, limit=MAX_JSON)
    except ValueError as exc:
        raise PackConformanceError('Corrupt JSON: ' + str(exc)) from exc
    if not isinstance(obj, dict):
        raise PackConformanceError('JSON object required')
    return obj


class PackConformanceValidator:
    def __init__(self, db_path, manifest_path=None, *, repo_root=ROOT):
        self.db_path = Path(db_path)
        self.manifest_path = Path(manifest_path) if manifest_path is not None else None
        self.repo_root = Path(repo_root)
        self.publication_approved = False
        self.is_verified = False
        self.language_code = None
        self.language_codes = set()

    def validate(self):
        self.is_verified = False
        self.language_code = None
        self.language_codes = set()
        if not self.db_path.is_file():
            raise FileNotFoundError(f'Pack not found: {self.db_path}')
        if self.db_path.stat().st_size > MAX_DATABASE:
            raise PackConformanceError('Database size limit exceeded')
        try:
            sources = load_verified_ledger(self.repo_root)
        except (OSError, ValueError, TypeError):
            sources = {}
        self.is_verified = bool(sources)
        schema = object_json((ROOT / 'standards/lexical/lexical.schema.json').read_bytes())
        self.validators = {kind: Draft202012Validator({
            '$ref': '#/$defs/' + kind, '$defs': schema['$defs']})
            for kind in ('lexeme', 'sense', 'translation', 'example', 'relation')}
        try:
            # All validation uses one bounded snapshot, including the manifest
            # digest. FTS integrity needs a write-shaped SQLite command; run it
            # only on this disposable copy, never on the supplied pack.
            with tempfile.TemporaryDirectory(prefix='reference-conformance-') as tmp:
                snapshot = Path(tmp) / 'candidate.sqlite'
                with self.db_path.open('rb') as source, snapshot.open('wb') as dest:
                    remaining = MAX_DATABASE + 1
                    while remaining:
                        chunk = source.read(min(65536, remaining))
                        if not chunk:
                            break
                        dest.write(chunk)
                        remaining -= len(chunk)
                if snapshot.stat().st_size > MAX_DATABASE:
                    raise PackConformanceError('Database size limit exceeded')
                manifest = self._manifest_entry(snapshot)
                with closing(sqlite3.connect(snapshot)) as db:
                    deadline = time.monotonic() + 20
                    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
                    db.execute('PRAGMA cache_size=-2048')
                    db.row_factory = sqlite3.Row
                    self._validate_database(db, sources, manifest)
        except sqlite3.Error as exc:
            raise PackConformanceError('SQLite error: ' + str(exc)) from exc
        return self.is_verified

    def _manifest_entry(self, snapshot):
        if self.manifest_path is None:
            return None
        if not self.manifest_path.is_file():
            raise PackConformanceError('Manifest file is missing')
        if self.manifest_path.stat().st_size > MAX_JSON:
            raise PackConformanceError('Manifest size limit exceeded')
        manifest = object_json(self.manifest_path.read_bytes())
        packs = manifest.get('packs')
        if not isinstance(packs, dict):
            raise PackConformanceError('Invalid manifest packs')
        matches = [meta for meta in packs.values() if isinstance(meta, dict)
                   and isinstance(meta.get('path'), str)
                   and (self.manifest_path.parent / meta['path']).resolve() == self.db_path.resolve()]
        if len(matches) != 1:
            raise PackConformanceError('Manifest must identify exactly one matching pack')
        meta = matches[0]
        digest = meta.get('sha256')
        if (not isinstance(digest, str) or len(digest) != 64
                or any(c not in '0123456789abcdef' for c in digest)
                or digest != compute_sha256(snapshot)):
            raise PackConformanceError('Hash mismatch or missing manifest SHA256')
        if type(meta.get('entry_count')) is not int or meta['entry_count'] < 1:
            raise PackConformanceError('Manifest entry_count must be a positive integer')
        return meta

    def _provenance(self, source, sources):
        if not isinstance(source, dict):
            raise PackConformanceError('Source JSON object required')
        sid = source.get('source_id')
        approved = sources.get(sid) if isinstance(sid, str) else None
        if (not approved or source.get('publication_approved') is not True
                or source.get('fixture_only') is not False
                or source.get('license_id') != approved['license']['id']
                or source.get('dataset_version') != approved['dataset_version']
                or source.get('retrieval_id') != approved['retrieval']['identity']
                or source.get('artifact_sha256') != approved['retrieval']['sha256']
                or source.get('origin_url') != approved['origin_url']
                or source.get('publisher') != approved['publisher']):
            self.is_verified = False

    def _record(self, raw, kind, sources):
        payload = object_json(raw)
        if next(self.validators[kind].iter_errors(payload), None) is not None:
            raise PackConformanceError(f'Invalid {kind} fields_json/payload_json')
        self._provenance(payload['source'], sources)
        if kind == 'lexeme':
            for group in ('articles', 'classifiers', 'inflections', 'conjugations', 'irregular_forms'):
                for form in payload.get('morphology', {}).get(group, []):
                    self._provenance(form.get('source', payload['source']), sources)
            for pronunciation in payload.get('pronunciations', []):
                self._provenance(pronunciation.get('source'), sources)
        elif kind == 'example':
            for translation in payload.get('translations', []):
                self._provenance(translation.get('source'), sources)
        return payload

    def _validate_database(self, db, sources, manifest):
        if [tuple(r) for r in db.execute('PRAGMA integrity_check')] != [('ok',)]:
            raise PackConformanceError('SQLite integrity check failed')
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise PackConformanceError('SQLite foreign-key check failed')
        if db.execute('PRAGMA user_version').fetchone()[0] != SQLITE_USER_VERSION:
            raise PackConformanceError('Expected user_version 2')
        metadata = dict(db.execute('SELECT key,value FROM metadata'))
        if not all(metadata.get(k) for k in ('contract_version', 'mapping_version', 'document_id')):
            raise PackConformanceError('Missing mandatory metadata fields')
        if metadata['contract_version'] != '1.0.0' or metadata['mapping_version'] != MAPPING_VERSION:
            raise PackConformanceError('Unsupported contract or mapping version')
        if [tuple(r) for r in db.execute('SELECT version,description FROM schema_migrations')] != [
                (MAPPING_VERSION, 'initial public v2 mapping')]:
            raise PackConformanceError('Unsupported schema migration')
        with closing(sqlite3.connect(':memory:')) as reference:
            reference.executescript(DDL)
            query = 'SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name'
            if [tuple(r) for r in db.execute(query)] != reference.execute(query).fetchall():
                raise PackConformanceError('Canonical SQLite v2 schema mismatch (including FTS5 and indexes)')
        count = db.execute('SELECT count(*) FROM lexicon').fetchone()[0]
        if not count:
            raise PackConformanceError('Pack is empty (0 lexicon rows)')
        if manifest is not None and count != manifest['entry_count']:
            raise PackConformanceError('Mismatched declared count in manifest')
        if 'terms_count' in metadata and metadata['terms_count'] != str(count):
            raise PackConformanceError('Mismatched declared count in metadata')
        if db.execute('SELECT count(*) FROM lexicon_fts').fetchone()[0] != count:
            raise PackConformanceError('FTS5 count mismatch')
        db.execute("INSERT INTO lexicon_fts(lexicon_fts,rank) VALUES('integrity-check',1)")
        # The reference producer derives CEFR from attested sense levels.
        # Index these once rather than issuing a query for each lexeme.
        cefr_by_lexeme = {}
        for sense in db.execute('SELECT lexeme_id, payload_json FROM senses'):
            payload = self._record(sense['payload_json'], 'sense', sources)
            for level in payload.get('levels', []):
                if level['framework_id'] == 'cefr':
                    cefr_by_lexeme.setdefault(sense['lexeme_id'], []).append(level['level_id'])
        for row in db.execute('SELECT rowid,* FROM lexicon ORDER BY rowid'):
            payload = self._record(row['fields_json'], 'lexeme', sources)
            source = object_json(row['source_json'])
            if source != payload['source']:
                raise PackConformanceError('Source projection mismatch')
            # The reference producer supports multilingual directed packs.
            # Each lexeme's language must match its own JSON projection.
            self.language_codes.add(row['language_code'])
            self.language_code = (next(iter(self.language_codes))
                                  if len(self.language_codes) == 1 else None)
            fields = {'id':'lexeme_id', 'surface':'surface', 'part_of_speech':'pos', 'pos':'pos',
                      'language_code':'language', 'script':'script', 'direction':'direction'}
            if any(row[col] != payload[key] for col, key in fields.items()):
                raise PackConformanceError('Invalid POS or lexeme payload projection mismatch')
            levels = cefr_by_lexeme.get(row['id'], [])
            expected_cefr = levels[0] if levels and len(set(levels)) == 1 else None
            if (row['dialect'] != payload.get('dialect')
                    or row['cefr_level'] != expected_cefr
                    or row['frequency_rank'] is not None):
                raise PackConformanceError('Lexicon dialect/CEFR/rank projection mismatch')
            if row['sort_key'] != sort_key(row['surface']):
                raise PackConformanceError('Invalid sort_key')
            glosses = {r[0] for r in db.execute('SELECT definition FROM senses WHERE lexeme_id=?', (row['id'],))}
            glosses.update(r[0] for r in db.execute('SELECT t.text FROM senses s JOIN translations t ON t.from_sense_id=s.sense_id WHERE s.lexeme_id=?', (row['id'],)))
            expected = (row['surface'], payload['lemma'], ' '.join(sorted(glosses)), row['language_code'])
            actual = db.execute('SELECT surface,lemma,gloss,language_code FROM lexicon_fts WHERE rowid=?', (row['rowid'],)).fetchone()
            if actual is None or tuple(actual) != expected:
                raise PackConformanceError('FTS5 payload projection mismatch')
        for table, kind in (('senses','sense'), ('translations','translation'), ('examples','example'), ('lexical_relations','relation')):
            for row in db.execute('SELECT * FROM ' + table):
                payload = self._record(row['payload_json'], kind, sources)
                columns = dict(row)
                if 'language_code' in columns:
                    columns['language'] = columns.pop('language_code')
                if table == 'examples':
                    link = db.execute('SELECT s.lexeme_id,l.language_code FROM senses s JOIN lexicon l ON l.id=s.lexeme_id WHERE s.sense_id=?', (row['sense_id'],)).fetchone()
                    if columns.pop('lexeme_id') != link[0] or payload['language'] != link[1]:
                        raise PackConformanceError('Example sense/language projection mismatch')
                if table == 'translations':
                    target = db.execute('SELECT l.language_code FROM senses s JOIN lexicon l ON l.id=s.lexeme_id WHERE s.sense_id=?', (row['to_sense_id'],)).fetchone()
                    if payload['language'] != target[0]:
                        raise PackConformanceError('Directed translation target language mismatch')
                columns.pop('payload_json')
                if any(payload.get(key) != value for key, value in columns.items()):
                    raise PackConformanceError(table + ' payload projection mismatch')
        union = ' UNION ALL '.join('SELECT ' + col + ' AS id FROM ' + table for table, col in (
            ('lexicon','id'), ('senses','sense_id'), ('translations','translation_id'),
            ('examples','example_id'), ('lexical_relations','relation_id')))
        if db.execute('SELECT id FROM (' + union + ') GROUP BY id HAVING count(*)>1 LIMIT 1').fetchone():
            raise PackConformanceError('Duplicate stable ID across record tables')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('db_path', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--structural-only', action='store_true', help='explicit QA only; never publication approval')
    args = parser.parse_args(argv)
    try:
        validator = PackConformanceValidator(args.db_path, args.manifest)
        verified = validator.validate()
    except (OSError, ValueError) as exc:
        print('FAILED: ' + str(exc), file=sys.stderr)
        return 1
    print(json.dumps({'structural_validation':'PASS', 'source_evidence_verified':verified,
                      'publication_approved':False}))
    return 0 if verified or args.structural_only else 2


if __name__ == '__main__':
    raise SystemExit(main())
