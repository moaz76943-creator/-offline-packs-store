"""Read-only direct Tatoeba alignment QA. Never licenses or publishes a pair.

Input snapshots must be obtained and rights-reviewed by GHA-01/Route 05. Matching a
source link is structural evidence, NOT independent semantic/editorial approval.
All indexes are SQLite-backed; no transitive, English-pivot or reverse inference.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path

SHA = re.compile(r'^[0-9a-f]{64}$')
ID = re.compile(r'^[1-9][0-9]*$')
PILOT = {'deu': 'de', 'ara': 'ar', 'eng': 'en', 'spa': 'es', 'fra': 'fr'}
MAX_LINE = 65_536
MAX_PAIRS = 100_000


class PairError(ValueError):
    """Fail-closed input, provenance or direct evidence validation error."""


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(65_536), b''):
            h.update(part)
    return h.hexdigest()


def _verify(path, sha):
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise PairError('INVALID_SOURCE_SHA')
    if not Path(path).is_file() or Path(path).is_symlink() or _sha(path) != sha:
        raise PairError('SOURCE_SHA_MISMATCH')


def _pin_verified(path, sha, directory):
    """Hash and copy from one open file so a later replacement cannot be parsed."""
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise PairError('INVALID_SOURCE_SHA')
    source = Path(path)
    if not source.is_file() or source.is_symlink():
        raise PairError('SOURCE_SHA_MISMATCH')
    dest = Path(directory) / f'{sha}.pinned'
    suffix = 0
    while dest.exists():
        suffix += 1
        dest = Path(directory) / f'{sha}-{suffix}.pinned'
    digest = hashlib.sha256()
    flags = os.O_RDONLY
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(source, flags)
    except OSError as exc:
        raise PairError('SOURCE_SHA_MISMATCH') from exc
    try:
        with os.fdopen(fd, 'rb') as stream, dest.open('wb') as out:
            for part in iter(lambda: stream.read(65_536), b''):
                digest.update(part)
                out.write(part)
    except OSError as exc:
        dest.unlink(missing_ok=True)
        raise PairError('SOURCE_SHA_MISMATCH') from exc
    if digest.hexdigest() != sha:
        dest.unlink(missing_ok=True)
        raise PairError('SOURCE_SHA_MISMATCH')
    os.chmod(dest, 0o444)
    return dest


def _json(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise PairError('DUPLICATE_JSON_KEY')
        out[key] = value
    return out


def _finite_float(raw):
    # json.loads accepts 1e999 as float('inf') even when NaN tokens are banned.
    value = float(raw)
    if not math.isfinite(value):
        raise PairError('NONFINITE_JSON')
    return value


def _check_json_unicode(value):
    # Escaped lone surrogates are accepted by json.loads but cannot be UTF-8.
    # Traverse bounded JSONL iteratively, including nested metadata and keys.
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            try:
                item.encode('utf-8', 'strict')
            except UnicodeEncodeError as exc:
                raise PairError('INVALID_UNICODE_JSON') from exc
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def _lines(path, fields=None):
    with Path(path).open('rb') as stream:
        number = 0
        while line := stream.readline(MAX_LINE + 1):
            number += 1
            if len(line) > MAX_LINE or not line.endswith(b'\n'):
                raise PairError(f'BAD_LINE_{number}')
            try:
                txt = line.decode('utf-8', 'strict').rstrip('\r\n')
                if fields is None:
                    data = json.loads(txt, object_pairs_hook=_json, parse_float=_finite_float,
                                      parse_constant=lambda _: (_ for _ in ()).throw(PairError('NONFINITE_JSON')))
                    _check_json_unicode(data)
                else:
                    data = txt.split('\t')
                    if len(data) != fields or any('\x00' in x for x in data):
                        raise PairError('INVALID_TSV_FIELDS')
            except PairError:
                raise
            except (UnicodeError, ValueError) as exc:
                raise PairError(f'INVALID_ROW_{number}') from exc
            yield data


def _side(side, original, cc0, language_map):
    if not isinstance(side, dict) or set(side) != {'source_id', 'sentence_id', 'language', 'text', 'author', 'license', 'origin_url'}:
        raise PairError('INVALID_SENTENCE_ENVELOPE')
    sid = side['sentence_id']
    if not isinstance(sid, str) or not ID.fullmatch(sid) or side['source_id'] != 'tatoeba':
        raise PairError('INVALID_SENTENCE_ID')
    matched = original.execute('SELECT lang,text,author FROM sentence WHERE id=?', (sid,)).fetchone()
    if matched is None or language_map.get(matched[0]) != side['language'] or matched[1:] != (side['text'], side['author']):
        raise PairError('SENTENCE_SOURCE_MISMATCH')
    if side['origin_url'] != 'https://tatoeba.org/en/sentences/show/' + sid:
        raise PairError('INVALID_ATTRIBUTION_URL')
    if not side['text'].strip() or not side['author'].strip() or not side['language']:
        raise PairError('MISSING_SENTENCE_EVIDENCE')
    cc0_match = cc0.execute('SELECT lang,text FROM cc0 WHERE id=?', (sid,)).fetchone()
    if side['license'] != ('CC0-1.0' if cc0_match == matched[:2] else 'CC-BY-2.0-FR'):
        raise PairError('LICENSE_CLAIM_MISMATCH')
    return sid, side['language'], cc0_match == matched[:2]


def audit_pairs(detailed, detailed_sha256, links, links_sha256, cc0_file, cc0_sha256,
                candidates, candidates_sha256, language_map, registered_languages, *, max_pairs=MAX_PAIRS):
    """Cross-check GHA-05 candidate against separately hashed source exports.

    Even an exact, reciprocal direct Tatoeba edge is REVIEW_REQUIRED. The Route05
    rights ledger and semantic-editorial attestation are intentionally not
    inferred from data, source license labels or an input-supplied approval flag.
    """
    if type(max_pairs) is not int or not 1 <= max_pairs <= MAX_PAIRS:
        raise PairError('INVALID_PAIR_BUDGET')
    if not isinstance(language_map, dict) or any(
        not isinstance(src, str) or not re.fullmatch('[a-z]{3}', src)
        or not isinstance(dst, str) or dst not in registered_languages
        for src, dst in language_map.items()
    ) or any(language_map.get(k) != v for k, v in PILOT.items()) or len(set(language_map.values())) != len(language_map):
        raise PairError('INVALID_CANONICAL_LANGUAGE_MAP')
    counters = Counter()
    with tempfile.TemporaryDirectory(prefix='gha-directed-pair-qa-') as directory:
        detailed, links, cc0_file, candidates = (
            _pin_verified(path, sha, directory)
            for path, sha in ((detailed, detailed_sha256), (links, links_sha256),
                              (cc0_file, cc0_sha256), (candidates, candidates_sha256)))
        with sqlite3.connect(str(Path(directory) / 'lookup.sqlite')) as db:
            db.executescript('''CREATE TABLE sentence(id TEXT PRIMARY KEY,lang TEXT NOT NULL,text TEXT NOT NULL,author TEXT NOT NULL);
                CREATE TABLE cc0(id TEXT PRIMARY KEY,lang TEXT NOT NULL,text TEXT NOT NULL,modified_at TEXT NOT NULL);
                CREATE TABLE link(src TEXT NOT NULL,dst TEXT NOT NULL,PRIMARY KEY(src,dst));
                CREATE TABLE seen(id TEXT PRIMARY KEY);''')
            for row in _lines(detailed, 6):
                if not ID.fullmatch(row[0]):
                    raise PairError('INVALID_ORIGINAL_SENTENCE_ID')
                try:
                    db.execute('INSERT INTO sentence VALUES (?,?,?,?)', (row[0], row[1], row[2], row[3]))
                except sqlite3.IntegrityError as exc:
                    raise PairError('DUPLICATE_ORIGINAL_SENTENCE') from exc
            db.commit()
            # Official sentences_CC0: id, language, text, date last modified.
            # Username comes exclusively from sentences_detailed, not CC0.
            for row in _lines(cc0_file, 4):
                if not ID.fullmatch(row[0]):
                    raise PairError('INVALID_CC0_SENTENCE_ID')
                try:
                    db.execute('INSERT INTO cc0 VALUES (?,?,?,?)', (row[0], row[1], row[2], row[3]))
                except sqlite3.IntegrityError as exc:
                    raise PairError('DUPLICATE_CC0_SENTENCE') from exc
            db.commit()
            for row in _lines(links, 2):
                if not all(ID.fullmatch(x) for x in row) or row[0] == row[1]:
                    raise PairError('INVALID_DIRECT_EDGE')
                try:
                    db.execute('INSERT INTO link VALUES (?,?)', row)
                except sqlite3.IntegrityError:
                    counters['duplicate_source_edges'] += 1
            db.commit()
            for pair in _lines(candidates):
                counters['candidates_inspected'] += 1
                if counters['candidates_inspected'] > max_pairs:
                    raise PairError('PAIR_BUDGET_EXCEEDED')
                if not isinstance(pair, dict) or pair.get('link_proof') != 'tatoeba_explicit_reciprocal' or pair.get('status') != 'VERIFIED_LINK_REVIEW_REQUIRED' or pair.get('source_snapshot_sha256') != detailed_sha256 or pair.get('links_sha256') != links_sha256:
                    raise PairError('INVALID_DIRECT_PROVENANCE')
                a, language_a, licensed_a = _side(pair.get('source'), db, db, language_map)
                b, language_b, licensed_b = _side(pair.get('target'), db, db, language_map)
                if a == b or language_a == language_b or a >= b:
                    raise PairError('INVALID_DIRECTION_OR_IDENTITY')
                for src, dst in ((a, b), (b, a)):
                    if db.execute('SELECT 1 FROM link WHERE src=? AND dst=?', (src, dst)).fetchone() is None:
                        raise PairError('NOT_AN_EXPLICIT_RECIPROCAL_DIRECT_LINK')
                expected_id = 'pair1_' + hashlib.sha256(
                    (json.dumps([a, b], sort_keys=True, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
                ).hexdigest()[:24]
                if pair.get('id') != expected_id:
                    raise PairError('INVALID_DETERMINISTIC_PAIR_ID')
                try:
                    db.execute('INSERT INTO seen VALUES (?)', (expected_id,))
                except sqlite3.IntegrityError as exc:
                    raise PairError('DUPLICATE_CANDIDATE_PAIR') from exc
                if licensed_a and licensed_b:
                    counters['cc0_direct_candidates_review_required'] += 1
                else:
                    counters['license_review_required'] += 1
            db.commit()
    return {'status': 'QA_ONLY_REVIEW_REQUIRED', 'publication_approved': False,
            'semantic_equivalence_approved': False, 'source_rights_approved': False,
            'source_snapshots': {'detailed': detailed_sha256, 'links': links_sha256,
                                 'cc0': cc0_sha256, 'candidates': candidates_sha256},
            'counts': dict(sorted(counters.items()))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('detailed', 'links', 'cc0', 'candidates'):
        parser.add_argument('--' + key, required=True)
        parser.add_argument('--' + key + '-sha256', required=True)
    parser.add_argument('--catalog', default='manifest.json')
    parser.add_argument('--mapping', help='reviewed JSON ISO-639-3 to canonical IDs')
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    manifest = json.loads(Path(args.catalog).read_text(encoding='utf-8'))
    languages = {entry['code'] for entry in manifest['languages']}
    if len(languages) != 100:
        raise PairError('MISSING_100_LANGUAGE_REGISTRY')
    mapping = json.loads(Path(args.mapping).read_text(encoding='utf-8')) if args.mapping else dict(PILOT)
    report = audit_pairs(args.detailed, args.detailed_sha256, args.links, args.links_sha256,
                         args.cc0, args.cc0_sha256, args.candidates, args.candidates_sha256,
                         mapping, languages)
    out = Path(args.out)
    temp = out.with_name(out.name + '.tmp')
    if out.is_symlink() or temp.is_symlink():
        raise PairError('UNSAFE_OUTPUT_PATH')
    # Exclusive create refuses pre-existing files and symlinks (including
    # dangling links) without following either. Never truncate an old .tmp.
    try:
        with temp.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
            stream.write('\n')
    except FileExistsError as exc:
        raise PairError('UNSAFE_OUTPUT_PATH') from exc
    os.replace(temp, out)
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
