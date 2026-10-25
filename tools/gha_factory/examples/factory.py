#!/usr/bin/env python3
"""Bounded offline Tatoeba snapshot importer. No approval, translation or audio is invented.

Production admission depends on Route 05's independently reviewed ledger and
separate sentence/language/sense/editorial attestations. This tool NEVER publishes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
import sqlite3
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

PILOT_MAP = {'deu': 'de', 'ara': 'ar', 'eng': 'en', 'spa': 'es', 'fra': 'fr'}
SHA = re.compile(r'^[0-9a-f]{64}$')
ID = re.compile(r'^[1-9][0-9]*$')
LICENSES = {'CC0-1.0', 'CC-BY-SA-4.0', 'GFDL-1.3-only', 'PUBLIC-DOMAIN'}
MAX_LINE = 32768
MAX_TEXT = 2000
MAX_RECORDS = 5_000_000
SCHEMA = '''
CREATE TABLE IF NOT EXISTS sentences (
 id TEXT PRIMARY KEY, language TEXT NOT NULL, text TEXT NOT NULL,
 author TEXT NOT NULL, text_sha TEXT NOT NULL, license TEXT NOT NULL,
 language_check TEXT NOT NULL, admitted INTEGER NOT NULL, bucket INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sentence_bucket ON sentences(bucket, id);
CREATE TABLE IF NOT EXISTS cc0(id TEXT PRIMARY KEY, language TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS edges(src TEXT NOT NULL, dst TEXT NOT NULL, PRIMARY KEY(src,dst));
CREATE TABLE IF NOT EXISTS audio(id TEXT NOT NULL, audio_id TEXT NOT NULL,
 author TEXT NOT NULL, license TEXT NOT NULL, attribution_url TEXT NOT NULL,
 PRIMARY KEY(id,audio_id));
'''


class Rejected(ValueError):
    """An untrustworthy input or unfulfilled dependency; never override silently."""


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def canonical(obj):
    return (json.dumps(obj, sort_keys=True, ensure_ascii=False,
                       separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def source_path(workspace, snapshot):
    if not isinstance(snapshot, dict) or not SHA.fullmatch(str(snapshot.get('sha256', ''))):
        raise Rejected('BLOCKED_SOURCE: missing immutable source SHA-256')
    name = snapshot.get('path')
    if not isinstance(name, str) or not name:
        raise Rejected('BLOCKED_SOURCE: source path missing')
    rel = Path(name)
    root = Path(workspace).resolve()
    if rel.is_absolute() or '..' in rel.parts or '.git' in rel.parts:
        raise Rejected('BLOCKED_SOURCE: unsafe source path')
    # resolve() follows symlinks; checking is_symlink() on the resolved
    # destination alone fails to catch linked files or parent directories.
    probe = root
    for component in rel.parts:
        probe = probe / component
        if probe.is_symlink():
            raise Rejected('BLOCKED_SOURCE: symlink snapshot path')
    path = (root / rel).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
        raise Rejected('BLOCKED_SOURCE: source missing or escapes workspace')
    if digest(path) != snapshot['sha256']:
        raise Rejected('BLOCKED_SOURCE: source SHA-256 mismatch')
    return path


def bounded_tsv(path, columns):
    with open(path, 'rb') as stream:
        line = 0
        while True:
            data = stream.readline(MAX_LINE + 1)
            if not data:
                break
            line += 1
            if len(data) > MAX_LINE:
                # Drain one physical line in bounded chunks, retaining neither
                # its bytes nor a decoded copy. Resume at the next real row.
                while data and not data.endswith(b'\n'):
                    data = stream.readline(MAX_LINE + 1)
                yield line, None, 'oversized_line'
                continue
            try:
                raw = data.decode('utf-8', 'strict').rstrip('\r\n')
                fields = raw.split('\t')
                if len(fields) != columns or any('\x00' in field for field in fields):
                    raise ValueError('bad_columns')
                yield line, fields, None
            except (UnicodeError, ValueError) as exc:
                yield line, None, type(exc).__name__


def verified_catalog(manifest, mappings):
    data = json.loads(Path(manifest).read_text(encoding='utf-8'))
    codes = [item['code'] for item in data['languages']]
    if len(codes) != 100 or len(set(codes)) != 100:
        raise Rejected('BLOCKED_DEPENDENCY: canonical 100-language manifest not available')
    result = dict(PILOT_MAP)
    for src, dst in mappings.items():
        if not re.fullmatch(r'[a-z]{3}', src) or dst not in codes:
            raise Rejected('BLOCKED_DEPENDENCY: invalid explicit language mapping')
        if src in result and result[src] != dst:
            raise Rejected('BLOCKED_DEPENDENCY: pilot language identity cannot be remapped')
        result[src] = dst
    if len(set(result.values())) != len(result):
        raise Rejected('BLOCKED_DEPENDENCY: ambiguous target language mapping')
    return {src: dst for src, dst in result.items() if dst in codes}


def script_check(text, language):
    # A script check can reject a mismatch, but NEVER prove same-script language identity.
    expected = {'ar': ('ARABIC',), 'de': ('LATIN',), 'en': ('LATIN',),
                'fr': ('LATIN',), 'es': ('LATIN',),
                'zh': ('CJK',), 'ja': ('HIRAGANA', 'KATAKANA', 'CJK')}.get(language)
    if not expected:
        return 'NEEDS_LANGUAGE_REVIEW'
    letters = [unicodedata.name(c, '') for c in text if unicodedata.category(c).startswith('L')]
    if not letters or sum(any(s in n for s in expected) for n in letters) * 10 < len(letters) * 6:
        return 'WRONG_SCRIPT'
    return 'NEEDS_LANGUAGE_REVIEW'


def source_approval(ledger, source_id, cc0_sha):
    """Actual Route 05 approval, never inferred from a licence name or a URL."""
    data = json.loads(Path(ledger).read_text(encoding='utf-8'))
    if (data.get('schema_version') != '1.0.0'
            or not isinstance(data.get('sources'), list)
            or any(not isinstance(s, dict) for s in data['sources'])):
        raise Rejected('BLOCKED_DEPENDENCY: malformed Route 05 ledger')
    matches = [s for s in data['sources'] if s.get('source_id') == source_id]
    if len(matches) != 1:
        return False
    src = matches[0]
    lic = src.get('license')
    retrieval = src.get('retrieval')
    review = src.get('review')
    if any(not isinstance(section, dict) for section in (lic, retrieval, review)):
        raise Rejected('BLOCKED_DEPENDENCY: malformed Route 05 ledger')
    for section, field in ((retrieval, 'url'), (lic, 'evidence_url'),
                           (review, 'decision_url')):
        if not isinstance(section.get(field), str):
            raise Rejected('BLOCKED_DEPENDENCY: malformed Route 05 ledger')
    evidence_sha = lic.get('evidence_sha256')
    # The CC0 export (not the mixed-licence detailed corpus) must be approved.
    return (src.get('kind') == 'examples' and src.get('status') == 'APPROVED_FOR_REDISTRIBUTION'
            and lic.get('id') == 'CC0-1.0' and lic.get('id') in LICENSES
            and retrieval.get('sha256') == cc0_sha and bool(retrieval.get('identity'))
            and retrieval['url'].startswith('https://')
            and isinstance(evidence_sha, str) and SHA.fullmatch(evidence_sha) is not None
            and lic['evidence_url'].startswith('https://')
            and bool(review.get('reviewer')) and review['decision_url'].startswith('https://'))


def make_cloze(sentence, annotation, senses, forms):
    """Use externally attested exact spans. Never fabricate or generate distractors."""
    if not sentence or sentence['admitted'] is not True:
        raise Rejected('BLOCKED_DEPENDENCY: sentence not approved')
    text = sentence['text']
    if (annotation.get('sentence_id') != sentence['id'] or
            annotation.get('language') != sentence['language'] or
            annotation.get('sentence_sha256') != hashlib.sha256(text.encode('utf-8')).hexdigest() or
            annotation.get('editorial_unambiguous') is not True or
            not annotation.get('editor_review_url', '').startswith('https://')):
        raise Rejected('REJECTED_EXERCISE: missing exact-text editorial review')
    start, end = annotation.get('start'), annotation.get('end')
    if (type(start) is not int or type(end) is not int or
            not 0 <= start < end <= len(text)):
        raise Rejected('REJECTED_EXERCISE: invalid span')
    answer = text[start:end]
    # Count canonical-equivalent occurrences, not just byte-identical spans.
    # Keep the original source text and editor-attested offsets unchanged.
    if (not answer.strip() or
            unicodedata.normalize('NFC', text).count(unicodedata.normalize('NFC', answer)) != 1):
        raise Rejected('REJECTED_EXERCISE: ambiguous answer span')
    sid = annotation.get('sense_id')
    lexeme = annotation.get('lexeme_id')
    sense = senses.get(sid)
    if (not sense or sense.get('language') != sentence['language'] or
            sense.get('lexeme_id') != lexeme or sense.get('approved') is not True):
        raise Rejected('REJECTED_EXERCISE: unapproved lexical sense')
    feats = annotation.get('features')
    if not isinstance(feats, dict) or not feats or not all(isinstance(k, str) and isinstance(v, str) for k,v in feats.items()):
        raise Rejected('REJECTED_EXERCISE: missing grammar features')
    key = (sentence['language'], sid, answer, tuple(sorted(feats.items())))
    if key not in forms:
        raise Rejected('REJECTED_EXERCISE: answer morphology unattested')
    distractors = annotation.get('distractors')
    if not isinstance(distractors, list) or not 2 <= len(distractors) <= 5:
        raise Rejected('REJECTED_EXERCISE: insufficient attested distractors')
    options = [answer]
    # Distinct choices must also be distinct under canonical Unicode spelling.
    # NFC preserves Arabic diacritics and Turkish dotted/dotless I distinctions.
    normalized_options = {unicodedata.normalize('NFC', answer).casefold()}
    for item in distractors:
        if not isinstance(item, dict) or not isinstance(item.get('surface'), str):
            raise Rejected('REJECTED_EXERCISE: bad distractor')
        surface = item['surface']
        other_sense = item.get('sense_id')
        # Another inflected form of the answer's own sense is also correct.
        # A non-string sense id cannot be used as a morphology key.
        if not isinstance(other_sense, str) or other_sense == sid:
            raise Rejected('REJECTED_EXERCISE: unsupported or ambiguous distractor')
        evidence = senses.get(other_sense)
        other_key = (sentence['language'], other_sense, surface, tuple(sorted(feats.items())))
        if (not surface.strip() or other_key not in forms or not evidence or
                evidence.get('language') != sentence['language'] or evidence.get('approved') is not True or
                unicodedata.normalize('NFC', surface).casefold() in normalized_options):
            raise Rejected('REJECTED_EXERCISE: unsupported or ambiguous distractor')
        options.append(surface)
        normalized_options.add(unicodedata.normalize('NFC', surface).casefold())
    return {'exercise_id': 'clz1_' + hashlib.sha256(canonical([sentence['id'], sid, start, end])).hexdigest()[:24],
            'sentence_id': sentence['id'], 'language': sentence['language'],
            'sense_id': sid, 'cloze': text[:start] + '____' + text[end:],
            'answer': answer, 'options': options, 'features': feats,
            'attribution': sentence.get('attribution'), 'status': 'VERIFIED_CANDIDATE_NOT_PUBLISHED'}


def run(workspace, config_path, catalog_path, ledger_path, output, *, partition_size=5000, deadline_seconds=900):
    if not 1 <= partition_size <= 20000 or not 1 <= deadline_seconds <= 3600:
        raise Rejected('invalid worker bounds')
    cfg = json.loads(Path(config_path).read_text(encoding='utf-8'))
    if cfg.get('source_id') != 'tatoeba' or not isinstance(cfg.get('snapshots'), dict):
        raise Rejected('BLOCKED_SOURCE: missing canonical Tatoeba source identity')
    names = cfg['snapshots']
    if not all(k in names for k in ('detailed', 'cc0', 'links')):
        raise Rejected('BLOCKED_SOURCE: missing immutable detailed, CC0 or links snapshot')
    paths = {k: source_path(workspace, v) for k, v in names.items()}
    mapping = verified_catalog(catalog_path, cfg.get('language_map', {}))
    approved = source_approval(ledger_path, cfg['source_id'], names['cc0']['sha256'])
    start_time = time.monotonic()
    out = Path(output).resolve()
    root = Path(workspace).resolve()
    if out == root or out.is_relative_to(root):
        raise Rejected('output must be outside immutable source workspace')
    # Build every output in an isolated sibling directory. A failed retry must
    # leave its last complete report, SQLite index and JSONL parts untouched.
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f'.{out.name}.staging-', dir=out.parent))
    con = sqlite3.connect(stage / 'candidates.sqlite')
    con.executescript(SCHEMA)
    counters = Counter()
    try:
        for table in ('sentences', 'cc0', 'edges', 'audio'):
            con.execute('DELETE FROM ' + table)
        for line, row, error in bounded_tsv(paths['cc0'], 4):
            if time.monotonic() - start_time > deadline_seconds or line > MAX_RECORDS:
                raise Rejected('BLOCKED_DEPENDENCY: CC0 worker budget exhausted; split snapshot upstream')
            if error or not ID.fullmatch(row[0]):
                counters['rejected_cc0'] += 1
                continue
            lang = mapping.get(row[1])
            if lang:
                try:
                    con.execute('INSERT INTO cc0 VALUES (?,?,?)', (row[0], lang, row[2]))
                except sqlite3.IntegrityError:
                    counters['rejected_cc0'] += 1
        con.commit()
        for line, row, error in bounded_tsv(paths['detailed'], 6):
            if time.monotonic() - start_time > deadline_seconds or line > MAX_RECORDS:
                raise Rejected('BLOCKED_DEPENDENCY: worker budget exhausted, split snapshot upstream')
            counters['sentences_processed'] += 1
            if error or not ID.fullmatch(row[0]) or len(row[2]) > MAX_TEXT or not row[2].strip() or not row[3].strip():
                counters['rejected_sentences'] += 1
                continue
            lang = mapping.get(row[1])
            if not lang:
                counters['rejected_wrong_or_unmapped_language'] += 1
                continue
            script = script_check(row[2], lang)
            if script == 'WRONG_SCRIPT':
                counters['rejected_wrong_or_unmapped_language'] += 1
                continue
            cc0 = con.execute('SELECT language,text FROM cc0 WHERE id=?', (row[0],)).fetchone()
            verified_cc0 = cc0 == (lang, row[2])
            license_id = 'CC0-1.0' if verified_cc0 else 'CC-BY-2.0-FR'
            # The pipeline does not possess an authenticated per-sentence language review.
            # Even an approved source therefore remains a candidate, never published.
            admit = 0
            bucket = int(hashlib.sha256(row[0].encode()).hexdigest()[:8], 16) % 256
            try:
                con.execute('INSERT INTO sentences VALUES (?,?,?,?,?,?,?,?,?)',
                            (row[0], lang, row[2], row[3], hashlib.sha256(row[2].encode()).hexdigest(),
                             license_id, script, admit, bucket))
                counters['candidate_sentences'] += 1
                if verified_cc0 and approved:
                    counters['licensed_cc0_candidates'] += 1
            except sqlite3.IntegrityError:
                counters['rejected_duplicate_sentence_id'] += 1
            if line % partition_size == 0:
                con.commit()
        con.commit()
        for line, row, error in bounded_tsv(paths['links'], 2):
            if time.monotonic() - start_time > deadline_seconds or line > MAX_RECORDS * 5:
                raise Rejected('BLOCKED_DEPENDENCY: link worker budget exhausted; split upstream')
            if error or not ID.fullmatch(row[0]) or not ID.fullmatch(row[1]) or row[0] == row[1]:
                counters['rejected_links'] += 1
                continue
            try:
                con.execute('INSERT INTO edges VALUES (?,?)', row)
            except sqlite3.IntegrityError:
                counters['rejected_duplicate_links'] += 1
            if line % partition_size == 0:
                con.commit()
        con.commit()
        if 'audio' in paths:
            for line, row, error in bounded_tsv(paths['audio'], 5):
                if time.monotonic() - start_time > deadline_seconds or line > MAX_RECORDS:
                    raise Rejected('BLOCKED_DEPENDENCY: audio worker budget exhausted; split upstream')
                if error or not ID.fullmatch(row[0]) or not ID.fullmatch(row[1]):
                    counters['rejected_audio'] += 1
                    continue
                # No audio is fetched; empty, NC and unknown licences are excluded.
                if row[3] not in ('CC BY 4.0', 'CC BY-SA 4.0', 'CC0 1.0') or not row[2].strip() or not row[4].startswith('https://'):
                    counters['excluded_audio_licensing'] += 1
                    continue
                try:
                    con.execute('INSERT INTO audio VALUES (?,?,?,?,?)', row)
                    counters['licensed_audio_metadata_only'] += 1
                except sqlite3.IntegrityError:
                    counters['rejected_audio'] += 1
            con.commit()
        pairs = con.execute('''SELECT a.id,b.id,a.language,b.language,a.text,b.text,
                   a.author,b.author,a.license,b.license
               FROM edges x JOIN edges y ON x.src=y.dst AND x.dst=y.src
               JOIN sentences a ON a.id=x.src JOIN sentences b ON b.id=x.dst
               WHERE x.src < x.dst AND a.language != b.language ORDER BY a.id,b.id''')
        candidates_dir = stage / 'verified_candidates'
        candidates_dir.mkdir(exist_ok=True)
        current = None
        index = 0
        try:
            for item in pairs:
                if (time.monotonic() - start_time > deadline_seconds or
                        counters['translation_pairs_verified'] >= MAX_RECORDS * 5):
                    raise Rejected('BLOCKED_DEPENDENCY: pair worker budget exhausted; split snapshot upstream')
                counters['translation_pairs_verified'] += 1
                a,b,la,lb,ta,tb,au,bu,lic_a,lic_b = item
                if la == 'ar' or lb == 'ar':
                    counters['arabic_direct_pairs'] += 1
                part = (counters['translation_pairs_verified'] - 1) // partition_size
                if part != index or current is None:
                    if current:
                        current.close()
                    index = part
                    current = open(candidates_dir / f'part-{index:05d}.jsonl', 'wb')
                obj = {'id': 'pair1_' + hashlib.sha256(canonical([a,b])).hexdigest()[:24],
                       'source': {'source_id': 'tatoeba', 'sentence_id': a, 'language': la,
                                  'text': ta, 'author': au, 'license': lic_a,
                                  'origin_url': 'https://tatoeba.org/en/sentences/show/' + a},
                       'target': {'source_id': 'tatoeba', 'sentence_id': b, 'language': lb,
                                  'text': tb, 'author': bu, 'license': lic_b,
                                  'origin_url': 'https://tatoeba.org/en/sentences/show/' + b},
                       'link_proof': 'tatoeba_explicit_reciprocal',
                       'source_snapshot_sha256': names['detailed']['sha256'],
                       'links_sha256': names['links']['sha256'],
                       'status': 'VERIFIED_LINK_REVIEW_REQUIRED'}
                current.write(canonical(obj))
        finally:
            if current:
                current.close()
        for file in candidates_dir.glob('part-*.jsonl'):
            if int(file.stem.split('-')[1]) > index or counters['translation_pairs_verified'] == 0:
                file.unlink()
        report = {'schema_version': 1, 'source_id': cfg['source_id'],
                  'source_license_and_sha': {k: {'sha256': v['sha256']} for k,v in names.items()},
                  'source_admission': 'LICENSED_CANDIDATES_ONLY' if approved else 'BLOCKED_DEPENDENCY_GHA01',
                  'queue_dispatch': 'NOT_DISPATCHED_GHA02',
                  'language_pairs': 'DIRECT_LINKS_ONLY',
                  'audio_license_status': 'METADATA_ONLY_NO_AUDIO_APPROVED',
                  'exercises_accepted': 0, 'published': 0,
                  'counts': dict(sorted(counters.items())),
                  'checkpoint': {'detailed_sha256': names['detailed']['sha256'],
                                 'links_sha256': names['links']['sha256'],
                                 'sentences_processed': counters['sentences_processed'],
                                 'pairs_written': counters['translation_pairs_verified']},
                  'status': 'BLOCKED_DEPENDENCY'}
        temp = stage / 'report.json.tmp'
        temp.write_bytes(canonical(report))
        os.replace(temp, stage / 'report.json')
        con.close()

        # Publish only after a fully successful import. Keep a restorable
        # complete previous generation if the second rename fails.
        previous = None
        if out.exists():
            previous = out.with_name(f'.{out.name}.previous-{uuid.uuid4().hex}')
            os.replace(out, previous)
        try:
            os.replace(stage, out)
        except OSError:
            if previous is not None:
                os.replace(previous, out)
            raise
        if previous is not None:
            shutil.rmtree(previous)
        return report
    finally:
        con.close()
        if stage.exists():
            shutil.rmtree(stage)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace', required=True)
    p.add_argument('--config', required=True)
    p.add_argument('--catalog', required=True)
    p.add_argument('--ledger', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--partition-size', type=int, default=5000)
    p.add_argument('--deadline-seconds', type=int, default=900)
    a = p.parse_args(argv)
    try:
        print(json.dumps(run(a.workspace,a.config,a.catalog,a.ledger,a.out,
                             partition_size=a.partition_size, deadline_seconds=a.deadline_seconds),
                         ensure_ascii=False, sort_keys=True))
        return 0
    except (Rejected, ValueError, OSError, sqlite3.Error) as exc:
        print('BLOCKED_DEPENDENCY: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
