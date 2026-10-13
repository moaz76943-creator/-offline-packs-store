#!/usr/bin/env python3
"""Evidence-only bounded sentence factory; read-only canonical contract adapter."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from tools.source_examples import pipeline as canonical

SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_LINE = 32768
SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
 id TEXT PRIMARY KEY, language TEXT NOT NULL, source_id TEXT NOT NULL,
 sentence_id TEXT NOT NULL, text TEXT NOT NULL, text_hash TEXT NOT NULL,
 fingerprint TEXT NOT NULL, exact_key TEXT NOT NULL, near_key TEXT NOT NULL,
 base_status TEXT NOT NULL, base_reasons TEXT NOT NULL,
 status TEXT NOT NULL, reasons TEXT NOT NULL, payload TEXT NOT NULL,
 change_hold INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_exact ON records(language,exact_key);
CREATE INDEX IF NOT EXISTS idx_near ON records(language,near_key);
CREATE INDEX IF NOT EXISTS idx_sentence ON records(source_id,sentence_id,language);
CREATE TABLE IF NOT EXISTS checkpoints (
 shard TEXT PRIMARY KEY, sha256 TEXT NOT NULL, rows INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS invalid_lines (
 shard TEXT NOT NULL, line INTEGER NOT NULL, reason TEXT NOT NULL,
 PRIMARY KEY(shard,line)
);
"""

def compact(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)

def digest(data):
    return hashlib.sha256(data.encode('utf-8') if isinstance(data, str) else data).hexdigest()

def file_digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(65536), b''):
            h.update(part)
    return h.hexdigest()

def surface(text):
    return unicodedata.normalize('NFC', ' '.join(text.split())).casefold()

def near_surface(text):
    return ''.join(ch for ch in surface(text) if ch.isalnum() or ch.isspace())

def evidence(attestation, text_hash, lang, reviewers):
    if not isinstance(attestation, dict) or attestation.get('sentence_sha256') != text_hash:
        return False
    reviewer = reviewers.get(attestation.get('reviewer_id'))
    if not reviewer or reviewer.get('approved') is not True or lang not in reviewer.get('languages', []):
        return False
    try:
        canonical.source_url(attestation.get('evidence_url'), 'attestation.evidence_url')
        return True
    except (ValueError, TypeError):
        return False

def validate_extended(row, ledger, sources, senses, rules, reviewers, allowed):
    """Canonical rejection cannot be overridden by new approval metadata."""
    status, reasons, grammar = canonical.validate(row, sources, senses, rules, reviewers)
    reasons = list(reasons)
    src, lang = row['source'], row['language']
    text_hash = digest(row['text'])
    if lang not in allowed:
        return 'REJECTED', sorted(set(reasons + ['language_not_registered'])), grammar
    origin = ledger.get(src['source_id'])
    if not origin or origin.get('kind') != 'examples' or origin.get('status') != 'APPROVED_FOR_REDISTRIBUTION':
        reasons.append('route05_example_approval_missing')
    else:
        retrieval, rights = origin.get('retrieval') or {}, origin.get('license') or {}
        if (src.get('dataset_version') != origin.get('dataset_version')
                or src.get('artifact_sha256') != retrieval.get('sha256')
                or src.get('publisher') != origin.get('publisher')
                or src.get('license') != rights.get('id')):
            return 'REJECTED', sorted(set(reasons + ['source_version_or_rights_conflict'])), grammar
        if not (retrieval.get('identity') and retrieval.get('url') and rights.get('evidence_sha256')
                and (origin.get('review') or {}).get('decision_url')):
            reasons.append('route05_evidence_incomplete')
    if not isinstance(src.get('dataset_version'), str) or not src['dataset_version'].strip():
        reasons.append('source_version_missing')
    if not isinstance(src.get('record_locator'), str) or not src['record_locator'].strip():
        reasons.append('source_locator_missing')
    if not isinstance(src.get('artifact_sha256'), str) or not SHA.fullmatch(src['artifact_sha256']):
        reasons.append('source_artifact_hash_missing')
    if src.get('source_class') not in ('attested_corpus', 'reviewed_editorial'):
        reasons.append('source_class_unverified')
    if src.get('source_class') == 'reviewed_editorial' and not evidence(
            row.get('editorial_rights_review'), text_hash, lang, reviewers):
        reasons.append('editorial_rights_review_missing')
    if not evidence(row.get('language_review'), text_hash, lang, reviewers):
        reasons.append('independent_language_review_missing')
    else:
        reasons = [reason for reason in reasons if reason != 'language_script_needs_review']
    if not evidence(row.get('annotation_review'), text_hash, lang, reviewers):
        reasons.append('context_register_grammar_review_missing')
    if row.get('translations') and not isinstance(row.get('translation_reviews'), list):
        reasons.append('translation_review_missing')
    if status == 'REJECTED':
        return status, sorted(set(reasons)), grammar
    return ('REQUIRES_REVIEW' if reasons else 'ACCEPTED'), sorted(set(reasons)), grammar

def load_catalog(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('schema_version') != '1.0.0' or len(data.get('languages', [])) != 100:
        raise ValueError('canonical 100-language registry required')
    codes = [row['id'] for row in data['languages']]
    if len(set(codes)) != 100:
        raise ValueError('duplicate registered language')
    return set(codes)

def load_ledger(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('schema_version') != '1.0.0' or not isinstance(data.get('sources'), list):
        raise ValueError('invalid Route05 ledger')
    sources = {source['source_id']: source for source in data['sources']}
    if len(sources) != len(data['sources']):
        raise ValueError('duplicate source ID')
    return sources

def safe_shard(root, item):
    name, expected = item.get('path'), item.get('sha256')
    if not isinstance(name, str) or not isinstance(expected, str) or not SHA.fullmatch(expected):
        raise ValueError('shard path and SHA-256 required')
    rel = Path(name)
    if rel.is_absolute() or '..' in rel.parts or '.git' in rel.parts:
        raise ValueError('unsafe shard path')
    path = (root / rel).resolve()
    if not path.is_relative_to(root) or path.is_symlink() or not path.is_file():
        raise ValueError('shard missing or unsafe')
    if file_digest(path) != expected:
        raise ValueError('immutable shard digest mismatch')
    return name, path, expected

def unique_pairs(items):
    out = {}
    for key, value in items:
        if key in out:
            raise ValueError('duplicate JSON key')
        out[key] = value
    return out

def process(manifest, workspace, db_file, out, *, catalog, ledger, senses, rules, reviewers):
    job = json.loads(Path(manifest).read_text(encoding='utf-8'))
    shards = job.get('shards')
    if job.get('schema_version') != 1 or not isinstance(shards, list) or not shards:
        raise ValueError('versioned nonempty shards manifest required')
    root = Path(workspace).resolve()
    source_ledger = load_ledger(ledger)
    source_grants = canonical.load_registry(ledger, 'sources')
    sense_catalog = canonical.load_registry(senses, 'senses')
    rule_catalog = canonical.load_registry(rules, 'rules')
    roster = canonical.load_registry(reviewers, 'reviewers')
    languages = load_catalog(catalog)
    db_file, out = Path(db_file).resolve(), Path(out).resolve()
    if db_file.is_relative_to(root) or out.is_relative_to(root):
        raise ValueError('database and outputs must remain outside source workspace')
    db_file.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    seen = set()
    with sqlite3.connect(db_file) as db:
        db.executescript(SCHEMA)
        for item in shards:
            name, path, expected = safe_shard(root, item)
            if name in seen:
                raise ValueError('duplicate manifest shard')
            seen.add(name)
            checkpoint = db.execute('SELECT sha256 FROM checkpoints WHERE shard=?', (name,)).fetchone()
            if checkpoint:
                if checkpoint[0] != expected:
                    raise ValueError('immutable checkpoint conflict')
                continue
            accepted_lines = 0
            with db:
                with path.open('rb') as stream:
                    for line_no, raw in enumerate(stream, 1):
                        if len(raw) > MAX_LINE:
                            db.execute('INSERT INTO invalid_lines VALUES (?,?,?)',
                                       (name, line_no, 'oversized_line'))
                            continue
                        try:
                            row = json.loads(raw.decode('utf-8', 'strict'), object_pairs_hook=unique_pairs)
                            if not isinstance(row, dict):
                                raise ValueError('row is not object')
                            status, reasons, grammar = validate_extended(
                                row, source_ledger, source_grants, sense_catalog,
                                rule_catalog, roster, languages)
                            record_id = canonical.key_for(row)
                            text, lang = row['text'], row['language']
                            fingerprint = digest(compact(row))
                            previous = db.execute(
                                'SELECT fingerprint,change_hold FROM records WHERE id=?', (record_id,)).fetchone()
                            hold = bool(previous and (previous[0] != fingerprint or previous[1]))
                            if hold:
                                status = 'REQUIRES_REVIEW'
                                reasons = sorted(set(reasons + ['immutable_sentence_revision']))
                            payload = compact({**row, 'id': record_id, 'text_sha256': digest(text),
                                               'grammar': grammar})
                            db.execute("""INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                              ON CONFLICT(id) DO UPDATE SET
                              base_status=excluded.base_status,
                              base_reasons=excluded.base_reasons,
                              status=excluded.status,reasons=excluded.reasons,
                              change_hold=excluded.change_hold""",
                              (record_id, lang, row['source']['source_id'], row['source']['sentence_id'],
                               text, digest(text), fingerprint, digest(surface(text)),
                               near_surface(text)[:12], status, compact(reasons), status,
                               compact(reasons), payload, int(hold)))
                            accepted_lines += 1
                        except (ValueError, TypeError, KeyError, UnicodeError, OverflowError) as exc:
                            db.execute('INSERT INTO invalid_lines VALUES (?,?,?)',
                                       (name, line_no, type(exc).__name__))
                if file_digest(path) != expected:
                    raise ValueError('source shard mutated during processing')
                db.execute('INSERT INTO checkpoints VALUES (?,?,?)',
                           (name, expected, accepted_lines))
        # Indexed, bounded scans. Derived status is recalculated every invocation.
        last_id = ''
        while True:
            batch = db.execute("""SELECT id,language,source_id,sentence_id,text,text_hash,
                exact_key,near_key,base_status,base_reasons,payload
                FROM records WHERE id>? ORDER BY id LIMIT 512""", (last_id,)).fetchall()
            if not batch:
                break
            for rec in batch:
                uid, lang, sid, sentence_id, text, text_hash, exact, near, status, raw_reasons, payload = rec
                reasons = json.loads(raw_reasons)
                other = db.execute(
                    'SELECT id FROM records WHERE language=? AND exact_key=? AND id!=? LIMIT 1',
                    (lang, exact, uid)).fetchone()
                if other:
                    reasons.append('exact_duplicate_requires_review')
                if len(near) >= 8:
                    candidates = db.execute("""SELECT id,text FROM records WHERE language=?
                        AND near_key=? AND id!=? AND exact_key!=? LIMIT 32""",
                        (lang, near, uid, exact))
                    if any(SequenceMatcher(None, surface(text), surface(other_text)).ratio() >= .92
                           for _, other_text in candidates):
                        reasons.append('near_duplicate_requires_review')
                row = json.loads(payload)
                for link in row.get('translations', []):
                    targets = db.execute("""SELECT text_hash FROM records WHERE
                         source_id=? AND sentence_id=? AND language=?""",
                         (link['target_source_id'], link['target_sentence_id'],
                          link['target_language'])).fetchall()
                    reviews = [att for att in row.get('translation_reviews', [])
                               if isinstance(att, dict) and all(
                                   att.get(field) == link.get(field) for field in
                                   ('target_source_id', 'target_sentence_id', 'target_language'))]
                    if (len(targets) != 1 or len(reviews) != 1
                            or reviews[0].get('target_sha256') != targets[0][0]
                            or not evidence(reviews[0], text_hash, lang, roster)):
                        reasons.append('translation_equivalence_unverified')
                if status == 'ACCEPTED' and reasons:
                    status = 'REQUIRES_REVIEW'
                db.execute('UPDATE records SET status=?,reasons=? WHERE id=?',
                           (status, compact(sorted(set(reasons))), uid))
            last_id = batch[-1][0]
        db.commit()
        counts = {lang: {'accepted': 0, 'rejected': 0, 'requires_review': 0}
                  for lang in sorted(languages)}
        unregistered_rejected = 0
        for lang, status, n in db.execute(
                'SELECT language,status,count(*) FROM records GROUP BY language,status'):
            if lang in counts:
                counts[lang][status.lower()] += n
            else:
                unregistered_rejected += n
        malformed = db.execute('SELECT count(*) FROM invalid_lines').fetchone()[0]
        with (out / 'candidates.jsonl').open('w', encoding='utf-8') as dest:
            for payload, status, raw_reasons in db.execute(
                    'SELECT payload,status,reasons FROM records ORDER BY language,id'):
                record = json.loads(payload)
                record.update(status=status, reasons=json.loads(raw_reasons))
                dest.write(compact(record) + '\n')
        totals = {key: sum(count[key] for count in counts.values())
                  for key in ('accepted', 'rejected', 'requires_review')}
        totals['rejected'] += unregistered_rejected
        report = {'schema_version': 1, 'languages': counts,
                  'unregistered_rejected': unregistered_rejected,
                  'totals': totals, 'malformed_unattributed': malformed,
                  'completed_shards': db.execute('SELECT count(*) FROM checkpoints').fetchone()[0],
                  'published': 0, 'output_kind': 'review_candidates_only',
                  'candidate_sha256': file_digest(out / 'candidates.jsonl')}
        (out / 'report.json').write_text(compact(report) + '\n', encoding='utf-8')
        return report

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('manifest', 'workspace', 'db', 'out', 'catalog', 'ledger',
                 'senses', 'rules', 'reviewers'):
        parser.add_argument('--' + flag, type=Path, required=True)
    args = parser.parse_args(argv)
    print(compact(process(args.manifest, args.workspace, args.db, args.out,
                          catalog=args.catalog, ledger=args.ledger,
                          senses=args.senses, rules=args.rules,
                          reviewers=args.reviewers)))
    return 0

if __name__ == '__main__':
    sys.exit(main())
