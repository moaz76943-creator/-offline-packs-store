"""Evidence-preserving, bounded admission partitions -> lexical contract 1.0.0.

This is a staging adapter, not a publisher. Admission's ACCEPTED_FOR_QUEUE
never grants publication rights. Every output is a single independent lexical
fixture document suitable for pack_v2.pipeline.compile_pack(fixture_only=True).
"""
import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from tools.pack_v2 import pipeline

MAX_MANIFEST = 8 * 1024 * 1024
MAX_PARTITION = 256 * 1024 * 1024
MAX_LINE = 1024 * 1024
MAX_DOC_BYTES = 4 * 1024 * 1024
SHA256 = re.compile(r'^[0-9a-f]{64}$')
ID = re.compile(r'^[a-z][a-z0-9._:-]{2,127}$')
POS = {
    'noun': 'noun', 'verb': 'verb', 'adj': 'adjective',
    'adjective': 'adjective', 'adv': 'adverb', 'adverb': 'adverb',
    'pron': 'pronoun', 'pronoun': 'pronoun', 'prep': 'preposition',
    'preposition': 'preposition', 'conj': 'conjunction',
    'conjunction': 'conjunction', 'intj': 'interjection',
    'interjection': 'interjection', 'det': 'determiner',
    'determiner': 'determiner', 'num': 'numeral', 'numeral': 'numeral',
    'particle': 'particle', 'classifier': 'classifier',
    'phrase': 'multiword',
}
SCRIPT_DIRECTIONS = {'Latn': 'ltr', 'Arab': 'rtl', 'Hebr': 'rtl',
                     'Cyrl': 'ltr', 'Grek': 'ltr', 'Deva': 'ltr'}


class AdapterError(ValueError):
    """Fail closed; no staging output is published."""


def _object_unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AdapterError('duplicate JSON property: ' + key)
        result[key] = value
    return result


def _reject_numeric(value):
    raise AdapterError('invalid JSON numeric constant: ' + value)


def _read_json(path, limit):
    if path.stat().st_size > limit:
        raise AdapterError('oversized input')
    return json.loads(path.read_text('utf-8'), object_pairs_hook=_object_unique,
                      parse_constant=_reject_numeric)


def _digest(path):
    result = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(65536), b''):
            result.update(block)
    return result.hexdigest()


def _check_sha(value, label):
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise AdapterError('invalid ' + label)


def _fingerprint(*parts):
    return hashlib.sha256('\x00'.join(map(str, parts)).encode('utf-8')).hexdigest()[:40]


def _partition_file(base, job):
    name = job.get('path')
    if not isinstance(name, str) or not re.fullmatch(r'partition-[0-9]{8}\.jsonl', name):
        raise AdapterError('unsafe partition filename')
    target = base / name
    if target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_PARTITION:
        raise AdapterError('missing, linked or oversized admission partition')
    _check_sha(job.get('sha256'), 'partition SHA256')
    if _digest(target) != job['sha256']:
        raise AdapterError('partition SHA256 mismatch')
    return target


def _load_contract(queue_path, repo_root, fixture_only):
    queue = _read_json(queue_path, MAX_MANIFEST)
    if (queue.get('schema_version') != '1.0.0' or queue.get('status') != 'ACCEPTED_FOR_QUEUE'
            or queue.get('publication_approved') is not False):
        raise AdapterError('BLOCKED_SOURCE: queue status is not staging-only')
    if not fixture_only:
        raise AdapterError('BLOCKED_SOURCE: admission queue cannot authorize publication')
    source_id, language = queue.get('source_id'), queue.get('language')
    if not isinstance(source_id, str) or not ID.fullmatch(source_id):
        raise AdapterError('invalid lexical source identity')
    if not isinstance(language, str) or not re.fullmatch(r'[a-z]{2,3}', language):
        raise AdapterError('invalid source language')
    for key in ('source_artifact_sha256', 'license_evidence_sha256'):
        _check_sha(queue.get(key), key)
    jobs = queue.get('jobs')
    if not isinstance(jobs, list) or not jobs or len(jobs) > 100000:
        raise AdapterError('missing/boundless admission jobs')
    ledger = _read_json(repo_root / 'legal/ledger/sources.json', MAX_MANIFEST)
    found = [s for s in ledger.get('sources', []) if s.get('source_id') == source_id]
    if len(found) != 1:
        raise AdapterError('BLOCKED_SOURCE: missing or ambiguous ledger provenance')
    source = found[0]
    retrieval, license_info = source.get('retrieval') or {}, source.get('license') or {}
    if (source.get('status') != 'FIXTURE_ONLY'
            or source.get('dataset_version') != queue.get('dataset_version')
            or retrieval.get('sha256') != queue['source_artifact_sha256']
            or license_info.get('evidence_sha256') != queue['license_evidence_sha256']
            or license_info.get('id') != 'LicenseRef-SyntheticTestFixture'):
        raise AdapterError('BLOCKED_SOURCE: fixture ledger provenance mismatch')
    if not all(isinstance(source.get(k), str) and source[k] for k in ('origin_url','publisher')):
        raise AdapterError('incomplete fixture provenance')
    if not isinstance(retrieval.get('identity'), str) or not retrieval['identity']:
        raise AdapterError('retrieval identity missing')
    registry = _read_json(repo_root / 'catalog/language_registry.v1.json', MAX_MANIFEST)
    script = next((row.get('default_script') for row in registry.get('languages', [])
                   if row.get('id') == language), None)
    if script not in SCRIPT_DIRECTIONS:
        raise AdapterError('unsupported/unverified script direction')
    source_template = {
        'source_id': source_id, 'origin_url': source['origin_url'],
        'publisher': source['publisher'], 'dataset_version': source['dataset_version'],
        'retrieval_id': retrieval['identity'], 'license_id': license_info['id'],
        'artifact_sha256': retrieval['sha256'],
        'publication_approved': False, 'fixture_only': True,
    }
    return queue, script, source_template


def _canonical(row, queue, script, source):
    if not isinstance(row, dict):
        raise AdapterError('non-object admission record')
    for key, expected in (('source_id', queue['source_id']),
                          ('dataset_version', queue['dataset_version']),
                          ('language', queue['language']),
                          ('license_id', source['license_id']),
                          ('source_artifact_sha256', queue['source_artifact_sha256']),
                          ('license_evidence_sha256', queue['license_evidence_sha256'])):
        if row.get(key) != expected:
            raise AdapterError('admission identity mismatch: ' + key)
    source_line = row.get('source_line')
    line_hash = row.get('source_line_sha256')
    if not isinstance(source_line, int) or isinstance(source_line, bool) or source_line <= 0:
        raise AdapterError('invalid original line locator')
    _check_sha(line_hash, 'original source line fingerprint')
    content = row.get('content')
    if not isinstance(content, dict) or not all(k in content for k in ('word', 'pos', 'senses')):
        raise AdapterError('incomplete admitted lexical content')
    word, pos_raw, definitions = content['word'], content['pos'], content['senses']
    if (not isinstance(word, str) or not word.strip() or len(word) > 256
            or not isinstance(pos_raw, str) or pos_raw not in POS
            or not isinstance(definitions, list) or not definitions):
        raise AdapterError('missing word, unknown POS, or missing definitions')
    if any(not isinstance(value, str) or not value.strip() for value in definitions):
        raise AdapterError('empty/nontext definition')
    # Source line content SHA is stable across partition reordering, unlike line number.
    # If upstream edits the raw record, it lacks a permanent entry ID: identity
    # reconciliation is required before production updates.
    token = _fingerprint(queue['source_id'], queue['language'], line_hash)
    prefix = queue['language']
    lexical_id = f'lex.{prefix}.{token}'
    attested = dict(source, record_locator=f'line:{source_line}:sha256:{line_hash}')
    lexeme = {'lexeme_id': lexical_id, 'language': prefix,
              'script': script, 'direction': SCRIPT_DIRECTIONS[script],
              'lemma': word, 'surface': word, 'pos': POS[pos_raw], 'source': attested}
    seen = {}
    senses = []
    for definition in definitions:
        # Preserve repeated identical glosses; they might represent distinct senses.
        key = _fingerprint(definition)
        occurrence = seen.get(key, 0)
        seen[key] = occurrence + 1
        sense_token = _fingerprint(token, definition, occurrence)
        senses.append({'sense_id': f'sense.{prefix}.{sense_token}',
                       'lexeme_id': lexical_id,
                       'concept_id': f'concept.{prefix}.{sense_token}',
                       'definition': definition, 'source': attested})
    return lexeme, senses


def convert(queue_path, out_dir, repo_root, *, fixture_only=False, max_lexemes=250):
    """Atomically create independent, bounded canonical JSON shards.

    Caller must never publish these shard documents as a complete language pack;
    each is an independently testable candidate for compile_pack fixture mode.
    """
    queue_path = Path(queue_path).resolve()
    repo_root = Path(repo_root).resolve()
    out_dir = Path(out_dir).absolute()
    if not isinstance(max_lexemes, int) or isinstance(max_lexemes, bool) or not 1 <= max_lexemes <= 1000:
        raise AdapterError('invalid maximum lexemes per document')
    if out_dir.exists() or out_dir.is_symlink() or not out_dir.parent.is_dir():
        raise AdapterError('output must not exist and parent must exist')
    queue, script, source = _load_contract(queue_path, repo_root, fixture_only)
    if not isinstance(queue.get('actual_accepted_records'), int) or queue['actual_accepted_records'] <= 0:
        raise AdapterError('invalid admitted record count')
    stage = Path(tempfile.mkdtemp(prefix='.lexical-stage-', dir=out_dir.parent))
    seen_db = sqlite3.connect(stage / '.seen.sqlite')
    count, sense_total, duplicates, files, lexemes, senses = 0, 0, 0, [], [], []
    used = 0

    def flush():
        nonlocal lexemes, senses, used
        if not lexemes:
            return
        idx = len(files)
        doc = {'contract_version': '1.0.0',
               'document_id': f'doc.{queue["language"]}.{_fingerprint(queue["source_id"], idx, lexemes[0]["lexeme_id"], lexemes[-1]["lexeme_id"])}',
               'lexemes': lexemes, 'senses': senses,
               'translations': [], 'examples': [], 'relations': []}
        raw = (pipeline.compact(doc) + '\n').encode('utf-8')
        if len(raw) > pipeline.MAX_JSON:
            raise AdapterError('canonical JSON exceeds compiler size limit')
        pipeline.validate_document(doc, queue['language'], repo_root, True)
        name = f'{queue["language"]}-{idx:08d}.json'
        (stage / name).write_bytes(raw)
        files.append(name)
        lexemes, senses, used = [], [], 0

    try:
        seen_db.execute('CREATE TABLE seen(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL)')
        jobs = queue['jobs']
        admitted = 0
        for index, job in enumerate(jobs):
            if (not isinstance(job, dict) or job.get('partition_index') != index
                    or job.get('source_id') != queue['source_id']
                    or job.get('dataset_version') != queue['dataset_version']
                    or job.get('language') != queue['language']
                    or job.get('category') != 'dictionary'
                    or job.get('license_id') != source['license_id']
                    or job.get('license_evidence_sha256') != queue['license_evidence_sha256']):
                raise AdapterError('admission partition descriptor mismatch')
            expected_resume = 'srcadm1-' + hashlib.sha256((pipeline.compact([queue['source_artifact_sha256'], {k:v for k,v in job.items() if k != 'resume_id'}]) + '\n').encode('utf-8')).hexdigest()[:40]
            if job.get('resume_id') != expected_resume:
                raise AdapterError('partition resume identity mismatch')
            expected = job.get('record_count')
            if not isinstance(expected, int) or isinstance(expected, bool) or expected <= 0:
                raise AdapterError('invalid partition count')
            part = _partition_file(queue_path.parent, job)
            actual = 0
            with part.open('rb') as stream:
                for raw in stream:
                    if (len(raw) > MAX_LINE or not raw.endswith(b'\n')
                            or raw.startswith(b'\xef\xbb\xbf')):
                        raise AdapterError('invalid/oversized admission JSONL record')
                    row = json.loads(raw.decode('utf-8'), object_pairs_hook=_object_unique,
                                     parse_constant=_reject_numeric)
                    lexical, meanings = _canonical(row, queue, script, source)
                    fp = _fingerprint(row['source_line_sha256'],
                                      pipeline.compact(row['content']))
                    old = seen_db.execute('SELECT fingerprint FROM seen WHERE id=?',
                                          (lexical['lexeme_id'],)).fetchone()
                    if old is not None:
                        if old[0] != fp:
                            raise AdapterError('conflicting deterministic lexeme ID')
                        duplicates += 1
                    else:
                        # Enforce compile_pack's per-row bound before accepting data.
                        pipeline.utf8(lexical)
                        for meaning in meanings:
                            pipeline.utf8(meaning)
                        footprint = len(pipeline.compact(lexical).encode('utf-8'))
                        footprint += sum(len(pipeline.compact(s).encode('utf-8')) for s in meanings)
                        if footprint > MAX_DOC_BYTES // 2:
                            raise AdapterError('single lexeme too large for bounded shard')
                        if lexemes and (len(lexemes) >= max_lexemes or used + footprint > MAX_DOC_BYTES):
                            flush()
                        lexemes.append(lexical)
                        senses.extend(meanings)
                        used += footprint
                        seen_db.execute('INSERT INTO seen VALUES (?,?)', (lexical['lexeme_id'], fp))
                        count += 1
                        sense_total += len(meanings)
                    actual += 1
                    admitted += 1
            if actual != expected:
                raise AdapterError('partition record_count mismatch')
        if admitted != queue['actual_accepted_records'] or not count:
            raise AdapterError('queue total mismatch/empty canonical content')
        flush()
        seen_db.close()
        (stage / '.seen.sqlite').unlink()
        summary = {'status': 'FIXTURE_ONLY_NOT_FOR_PUBLICATION',
                   'source_id': queue['source_id'], 'language': queue['language'],
                   'accepted_records': admitted, 'converted_lexemes': count,
                   'converted_senses': sense_total, 'deduplicated_records': duplicates,
                   'documents': files,
                   'note': 'Documents are bounded independent shards; not a whole-language pack.'}
        (stage / 'report.json').write_text(pipeline.compact(summary) + '\n', encoding='utf-8')
        if out_dir.exists() or out_dir.is_symlink():
            raise AdapterError('output was concurrently created')
        stage.rename(out_dir)
        return summary
    finally:
        try:
            seen_db.close()
        except Exception:
            pass
        if stage.exists():
            shutil.rmtree(stage)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queue', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--fixture-only', action='store_true')
    parser.add_argument('--max-lexemes', type=int, default=250)
    args = parser.parse_args(argv)
    try:
        result = convert(args.queue, args.out, args.repo_root,
                         fixture_only=args.fixture_only, max_lexemes=args.max_lexemes)
    except (AdapterError, ValueError, OSError) as exc:
        print('BLOCKED_SOURCE: ' + str(exc), file=sys.stderr)
        return 2
    print(pipeline.compact(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
