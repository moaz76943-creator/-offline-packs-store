#!/usr/bin/env python3
"""Offline, fail-closed example-sentence ingestion. Standard library only.

Publication requires independently supplied source approvals, sense/rule contracts,
and a trusted reviewer roster with per-record evidence. A web URL alone is NOT
proof of approval. No network, machine translation, CEFR inference, or LLM calls.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA_VERSION = 1
SITUATIONS = frozenset('greetings travel health work food home emergencies shopping administration study'.split())
CONSTRUCTIONS = frozenset(('positive', 'negative', 'interrogative'))
REGISTERS = frozenset(('formal', 'neutral', 'informal', 'colloquial', 'unknown'))
POLITENESS = frozenset(('polite', 'familiar', 'honorific', 'unspecified', 'unknown'))
CEFR = frozenset(('A1', 'A2', 'B1', 'B2', 'C1', 'C2'))
LICENSE_URLS = {
    'CC-BY-2.0-FR': 'https://creativecommons.org/licenses/by/2.0/fr/',
    'CC0-1.0': 'https://creativecommons.org/publicdomain/zero/1.0/',
    'CC-BY-4.0': 'https://creativecommons.org/licenses/by/4.0/',
    'CC-BY-SA-4.0': 'https://creativecommons.org/licenses/by-sa/4.0/',
    'PUBLIC-DOMAIN': 'https://creativecommons.org/publicdomain/mark/1.0/',
}
LICENSES = frozenset(LICENSE_URLS)
SCOPED = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,150}$')
LANG = re.compile(r'^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$')
ALLOWED_SCRIPTS = {
    'ar': 'ARABIC', 'fa': 'ARABIC', 'ur': 'ARABIC', 'de': 'LATIN',
    'en': 'LATIN', 'es': 'LATIN', 'fr': 'LATIN', 'ja': 'CJK', 'zh': 'CJK'
}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS examples (
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL, sentence_id TEXT NOT NULL,
 language TEXT NOT NULL, situation TEXT NOT NULL, context_id TEXT NOT NULL,
 sense_index TEXT NOT NULL, duplicate_key TEXT NOT NULL,
 input_hash TEXT NOT NULL, change_hold INTEGER NOT NULL DEFAULT 0,
 raw_json TEXT NOT NULL, status TEXT NOT NULL, reasons_json TEXT NOT NULL,
 export_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_example_lookup ON examples(language,situation,status,id);
CREATE INDEX IF NOT EXISTS ix_example_duplicates ON examples(duplicate_key);
CREATE TABLE IF NOT EXISTS example_senses (
 id TEXT NOT NULL, sense_id TEXT NOT NULL,
 PRIMARY KEY(id,sense_id), FOREIGN KEY(id) REFERENCES examples(id)
);
CREATE INDEX IF NOT EXISTS ix_example_sense ON example_senses(sense_id,id);
CREATE TABLE IF NOT EXISTS invalid_lines (line INTEGER PRIMARY KEY, error_kind TEXT NOT NULL);
'''


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha(value):
    if isinstance(value, str):
        value = value.encode('utf-8')
    return hashlib.sha256(value).hexdigest()


def nonempty(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 20000:
        raise ValueError(label + ' must be nonempty bounded text')
    if any((ord(c) < 32 and c not in '\n\t') or ord(c) == 127 for c in value):
        raise ValueError(label + ' has control characters')
    return value


def source_url(value, label):
    nonempty(value, label)
    parts = urlsplit(value)
    if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
            or parts.fragment or parts.port not in (None, 443)):
        raise ValueError(label + ' must be a public HTTPS source URL')
    # No host extraction into external queries or redirects. Local string validation only.
    if parts.hostname in ('localhost', '127.0.0.1', '0.0.0.0', '::1') or parts.hostname.endswith('.local'):
        raise ValueError(label + ' is not public')
    return value


def load_registry(path, field):
    if not path:
        return {}
    root = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(root, dict):
        raise ValueError('invalid registry ' + field)
    # Accept the repository's independent, versioned source ledger and lexical
    # contract verbatim. Never treat synthetic lexical fixtures as approved senses.
    if field == 'sources' and root.get('schema_version') == '1.0.0':
        if not isinstance(root.get('sources'), list):
            raise ValueError('invalid public legal source ledger')
        out = {}
        for item in root['sources']:
            sid = item.get('source_id') if isinstance(item, dict) else None
            if not sid or sid in out:
                raise ValueError('invalid/duplicate canonical legal source ID')
            lic = item.get('license') or {}
            url = item.get('origin_url', '')
            parsed = urlsplit(url)
            out[sid] = {
                'source_id': sid, 'publisher': item.get('publisher'),
                'license': lic.get('id'),
                'origin_prefix': parsed.scheme + '://' + parsed.netloc + '/' if parsed.hostname else '',
                'redistribution_approved': item.get('status') == 'APPROVED_FOR_REDISTRIBUTION'
                    and item.get('kind') == 'examples' and bool(item.get('review'))
                    and bool((item.get('retrieval') or {}).get('sha256')),
                'share_alike_obligations_verified': bool(item.get('review')),
                'public_domain_basis_verified': bool(lic.get('public_domain_proof')),
            }
        return out
    if field == 'senses' and root.get('contract_version') == '1.0.0':
        if not isinstance(root.get('lexemes'), list) or not isinstance(root.get('senses'), list):
            raise ValueError('invalid canonical lexical contract')
        lexemes = {x['lexeme_id']: x for x in root['lexemes']}
        out = {}
        for item in root['senses']:
            src = item.get('source') or {}
            lex = lexemes.get(item.get('lexeme_id'), {})
            lex_src = lex.get('source') or {}
            if (src.get('publication_approved') is True and src.get('fixture_only') is False
                    and lex_src.get('publication_approved') is True and lex_src.get('fixture_only') is False):
                sid = item['sense_id']
                if sid in out:
                    raise ValueError('duplicate canonical sense')
                out[sid] = {'sense_id': sid, 'lexeme_id': item['lexeme_id'], 'language': lex['language']}
        return out
    if root.get('schema_version') != SCHEMA_VERSION or not isinstance(root.get(field), list):
        raise ValueError('invalid registry ' + field)
    key = {'sources': 'source_id', 'senses': 'sense_id', 'rules': 'rule_id', 'reviewers': 'id'}[field]
    out = {}
    for item in root[field]:
        if not isinstance(item, dict) or not isinstance(item.get(key), str) or item[key] in out:
            raise ValueError('duplicate/invalid ' + field + ' key')
        out[item[key]] = item
    return out


def script_match(text, lang):
    expected = ALLOWED_SCRIPTS.get(lang.split('-')[0])
    if not expected:
        return None  # cannot establish language identity: human review required
    names = [unicodedata.name(c, '') for c in text if unicodedata.category(c).startswith('L')]
    if not names:
        return False
    if expected == 'CJK':
        return any(any(key in n for key in ('CJK', 'HIRAGANA', 'KATAKANA')) for n in names)
    return sum(expected in n for n in names) / len(names) >= 0.65


def key_for(row):
    src = row['source']
    identity = [src['source_id'], str(src['sentence_id']), row['language'], row['context_id']]
    return 'ex1_' + sha(canonical(identity))[:24]


def duplicate_key(row):
    # NFC/casefold protects combining marks; punctuation is intentionally meaningful.
    norm = unicodedata.normalize('NFC', ' '.join(row['text'].split())).casefold()
    senses = sorted(x['sense_id'] for x in row.get('sense_refs', []))
    return sha(canonical([row['language'], norm, row['context_id'], senses]))


def validate(row, licenses, senses, rules, reviewers, changed=False):
    reasons = []
    hard = []
    if not isinstance(row, dict) or row.get('schema_version') != SCHEMA_VERSION:
        raise ValueError('invalid sentence record/schema_version')
    src = row.get('source')
    if not isinstance(src, dict):
        raise ValueError('source metadata missing')
    for field in ('source_id', 'sentence_id', 'publisher', 'author', 'license', 'attribution'):
        nonempty(src.get(field), 'source.' + field)
    nonempty(src.get('origin_url'), 'source.origin_url')
    source_url(src['origin_url'], 'source.origin_url')
    source_url(src.get('license_url'), 'source.license_url')
    if not SCOPED.fullmatch(src['source_id']) or not SCOPED.fullmatch(src['sentence_id']):
        raise ValueError('unsafe source identifier')
    if src['license'] not in LICENSES:
        hard.append('unsupported_or_unknown_license')
    elif src['license_url'] != LICENSE_URLS[src['license']]:
        hard.append('license_notice_url_mismatch')
    if src['author'] not in src['attribution'] or src['origin_url'] not in src['attribution']:
        hard.append('incomplete_author_attribution')
    lic = licenses.get(src['source_id'])
    if lic is None:
        reasons.append('source_approval_not_available')
    elif (lic.get('license') != src['license'] or lic.get('publisher') != src['publisher']
          or not src['origin_url'].startswith(lic.get('origin_prefix', 'invalid:'))):
        hard.append('source_license_ledger_conflict')
    elif lic.get('redistribution_approved') is not True:
        reasons.append('redistribution_not_approved')
    elif src['license'] == 'CC-BY-SA-4.0' and lic.get('share_alike_obligations_verified') is not True:
        reasons.append('share_alike_obligations_unresolved')
    elif src['license'] == 'PUBLIC-DOMAIN' and lic.get('public_domain_basis_verified') is not True:
        reasons.append('public_domain_basis_unverified')
    nonempty(row.get('text'), 'text')
    if len(row['text']) > 2000:
        raise ValueError('sentence too long')
    if not LANG.fullmatch(row.get('language', '')):
        raise ValueError('invalid language BCP-47 identity')
    match = script_match(row['text'], row['language'])
    if match is False:
        hard.append('wrong_or_unsupported_script')
    elif match is None:
        reasons.append('language_script_needs_review')
    if row.get('privacy_class') != 'public':
        hard.append('private_or_unapproved_content')
    if not SCOPED.fullmatch(row.get('context_id', '')):
        raise ValueError('invalid semantic context id')
    for field, accepted in (('situation', SITUATIONS), ('construction', CONSTRUCTIONS),
                            ('register', REGISTERS), ('politeness', POLITENESS)):
        if row.get(field) not in accepted:
            raise ValueError('invalid ' + field)
    if row.get('dialect') is not None and not isinstance(row['dialect'], str):
        raise ValueError('invalid dialect')
    for field in ('sentence_cefr', 'word_cefr'):
        if row.get(field) is not None and row[field] not in CEFR:
            hard.append('unsupported_' + field)
    refs = row.get('sense_refs')
    if not isinstance(refs, list):
        raise ValueError('sense_refs must be list')
    if not refs:
        reasons.append('no_approved_lexical_sense')
    for ref in refs:
        if not isinstance(ref, dict):
            raise ValueError('invalid sense ref')
        sid = nonempty(ref.get('sense_id'), 'sense_id')
        lexeme = nonempty(ref.get('lexeme_id'), 'lexeme_id')
        item = senses.get(sid)
        if not item:
            reasons.append('sense_contract_unavailable:' + sid)
        elif item.get('language') != row['language'] or item.get('lexeme_id') != lexeme:
            hard.append('sense_contract_mismatch:' + sid)
    grammar = []
    gr = row.get('grammar_refs')
    if not isinstance(gr, list):
        raise ValueError('grammar_refs must be list')
    for ref in gr:
        if not isinstance(ref, dict):
            raise ValueError('invalid grammar ref')
        rule_id = nonempty(ref.get('rule_id'), 'grammar.rule_id')
        rule = rules.get(rule_id)
        if rule is None:
            reasons.append('grammar_contract_unavailable:' + rule_id)
            continue
        if rule.get('language') != row['language']:
            hard.append('wrong_language_grammar_rule:' + rule_id)
            continue
        for dimension, allowed in (('case', 'allowed_cases'), ('agreement', 'allowed_agreements')):
            if dimension in ref and ref[dimension] not in rule.get(allowed, []):
                hard.append('grammar_' + dimension + '_contradiction:' + rule_id)
        explanation = rule.get('explanation')
        if not isinstance(explanation, str) or not explanation.strip():
            reasons.append('unverified_grammar_explanation:' + rule_id)
            continue
        grammar.append({'rule_id': rule_id, 'explanation': explanation,
                        **{k: ref[k] for k in ('case', 'agreement') if k in ref}})
    trans = row.get('translations')
    if not isinstance(trans, list):
        raise ValueError('translations must be list')
    for item in trans:
        if not isinstance(item, dict):
            raise ValueError('malformed translation link')
        for field in ('target_source_id', 'target_sentence_id', 'target_language', 'direction', 'evidence_url'):
            nonempty(item.get(field), 'translation.' + field)
        source_url(item['evidence_url'], 'translation.evidence_url')
        if not (LANG.fullmatch(item['target_language']) and item['direction'] == row['language'] + '_to_' + item['target_language']):
            hard.append('translation_direction_mismatch')
        if item['target_source_id'] == src['source_id'] and item['target_sentence_id'] == src['sentence_id']:
            hard.append('self_translation_link')
    review = row.get('review')
    text_hash = sha(row['text'])
    if changed:
        reasons.append('changed_content_requires_new_evidence')
    if not isinstance(review, dict) or review.get('decision') != 'approved':
        reasons.append('independent_pedagogical_review_missing')
    elif (review.get('sentence_sha256') != text_hash or not review.get('evidence_url')):
        reasons.append('review_evidence_mismatch')
    else:
        source_url(review['evidence_url'], 'review.evidence_url')
        reviewer = reviewers.get(review.get('reviewer_id'))
        if not reviewer or reviewer.get('approved') is not True or row['language'] not in reviewer.get('languages', []):
            reasons.append('reviewer_not_authorized')
    if row.get('sentence_cefr') is not None:
        # CEFR requires independent evidence even when word-level CEFR is known.
        if not isinstance(row.get('cefr_evidence_url'), str):
            reasons.append('sentence_cefr_proof_missing')
        else:
            source_url(row['cefr_evidence_url'], 'cefr_evidence_url')
    if hard:
        status = 'REJECTED'
    elif reasons:
        status = 'REQUIRES_REVIEW'
    else:
        status = 'ACCEPTED'
    return status, sorted(set(hard + reasons)), grammar


def _initialize(db):
    db.executescript(SCHEMA)
    db.execute('PRAGMA foreign_keys=ON')


def _pack_write(path, chunks):
    """Deterministic gzip with no timestamp or original filename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as dest:
        with gzip.GzipFile(filename='', mode='wb', fileobj=dest, mtime=0, compresslevel=9) as gz:
            for chunk in chunks:
                gz.write(chunk.encode('utf-8'))


def _write_results(db, dest):
    dest.mkdir(parents=True, exist_ok=True)
    (dest / 'accepted').mkdir(exist_ok=True)
    languages = [x[0] for x in db.execute("SELECT DISTINCT language FROM examples WHERE status='ACCEPTED' ORDER BY language")]
    for old in (dest / 'accepted').glob('*.jsonl.gz'):
        if old.stem.removesuffix('.jsonl') not in languages:
            old.unlink()
    for lang in languages:
        rows = db.execute("SELECT export_json FROM examples WHERE status='ACCEPTED' AND language=? ORDER BY id", (lang,))
        _pack_write(dest / 'accepted' / (lang + '.jsonl.gz'), (x[0] + '\n' for x in rows))
    for status, filename in [('REQUIRES_REVIEW', 'requires_review.jsonl'), ('REJECTED', 'rejected.jsonl')]:
        with (dest / filename).open('w', encoding='utf-8', newline='\n') as handle:
            for (content,) in db.execute('SELECT export_json FROM examples WHERE status=? ORDER BY id', (status,)):
                handle.write(content + '\n')


def ingest(source_path, db_path, out_dir, ledger_path=None, sense_path=None, rule_path=None, reviewer_path=None):
    """Stream JSONL into on-disk index, retaining earlier IDs and review holds."""
    licenses = load_registry(ledger_path, 'sources')
    senses = load_registry(sense_path, 'senses')
    rules = load_registry(rule_path, 'rules')
    reviewers = load_registry(reviewer_path, 'reviewers')
    db_path, out_dir = Path(db_path), Path(out_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    batch = Counter()
    with sqlite3.connect(db_path) as db:
        _initialize(db)
        db.execute('DELETE FROM invalid_lines')
        with Path(source_path).open('r', encoding='utf-8') as stream:
            for lineno, line in enumerate(stream, 1):
                if not line.strip():
                    batch['invalid_rows'] += 1
                    db.execute('INSERT INTO invalid_lines VALUES (?,?)', (lineno, 'BlankLine'))
                    continue
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError('must be an object')
                    record_id = key_for(row)
                    fingerprint = sha(canonical({k: v for k, v in row.items() if k not in ('review', 'cefr_evidence_url')}))
                    previous = db.execute('SELECT input_hash,change_hold FROM examples WHERE id=?', (record_id,)).fetchone()
                    change_hold = int(bool(previous and (previous[0] != fingerprint or previous[1])))
                    status, reasons, grammar = validate(row, licenses, senses, rules, reviewers, bool(change_hold))
                    semantic = [r['sense_id'] for r in row['sense_refs']]
                    export = {**row, 'id': record_id, 'status': status, 'reasons': reasons,
                              'grammar': grammar, 'text_sha256': sha(row['text'])}
                    dupe = duplicate_key(row)
                    db.execute('INSERT INTO examples VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) '
                               'ON CONFLICT(id) DO UPDATE SET source_id=excluded.source_id, sentence_id=excluded.sentence_id, '
                               'language=excluded.language,situation=excluded.situation,context_id=excluded.context_id, '
                               'sense_index=excluded.sense_index,duplicate_key=excluded.duplicate_key,input_hash=excluded.input_hash, '
                               'change_hold=excluded.change_hold,raw_json=excluded.raw_json,status=excluded.status, '
                               'reasons_json=excluded.reasons_json,export_json=excluded.export_json',
                               (record_id, row['source']['source_id'], row['source']['sentence_id'], row['language'],
                                row['situation'], row['context_id'], canonical(semantic), dupe, fingerprint,
                                change_hold, canonical(row), status, canonical(reasons), canonical(export)))
                    db.execute('DELETE FROM example_senses WHERE id=?', (record_id,))
                    db.executemany('INSERT INTO example_senses VALUES (?,?)', [(record_id, s) for s in sorted(set(semantic))])
                    batch['upserted'] += 1
                except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                    # No raw record or personal data is printed/logged; invalid JSONL is accounted for.
                    batch['invalid_rows'] += 1
                    db.execute('INSERT INTO invalid_lines VALUES (?,?)', (lineno, type(exc).__name__))
        # Resolve relations against complete persisted corpus, regardless of ingestion order.
        for record_id, dup in db.execute('SELECT id,duplicate_key FROM examples ORDER BY id'):
            stored = db.execute('SELECT raw_json,status,reasons_json,export_json FROM examples WHERE id=?', (record_id,)).fetchone()
            row, status, reasons, exported = json.loads(stored[0]), stored[1], json.loads(stored[2]), json.loads(stored[3])
            if db.execute('SELECT count(*) FROM examples WHERE duplicate_key=?', (dup,)).fetchone()[0] > 1:
                reasons.append('duplicate_same_context')
            for trans in row['translations']:
                matches = db.execute('SELECT count(*) FROM examples WHERE source_id=? AND sentence_id=? AND language=?',
                                     (trans['target_source_id'], trans['target_sentence_id'], trans['target_language'])).fetchone()[0]
                if matches == 0:
                    reasons.append('translation_target_unresolved:' + trans['target_sentence_id'])
                elif matches > 1:
                    reasons.append('translation_target_context_ambiguous:' + trans['target_sentence_id'])
            if reasons and status == 'ACCEPTED':
                status = 'REQUIRES_REVIEW'
            exported['status'] = status
            exported['reasons'] = sorted(set(reasons))
            db.execute('UPDATE examples SET status=?,reasons_json=?,export_json=? WHERE id=?',
                       (status, canonical(exported['reasons']), canonical(exported), record_id))
        db.commit()
        _write_results(db, out_dir)
        if batch['invalid_rows']:
            with (out_dir / 'rejected.jsonl').open('a', encoding='utf-8') as handle:
                for lineno, reason in db.execute('SELECT line,error_kind FROM invalid_lines ORDER BY line'):
                    handle.write(canonical({'status': 'REJECTED', 'reason': 'malformed_input:' + reason, 'line': lineno}) + '\n')
        summary = dict.fromkeys(('accepted', 'rejected', 'requires_review'), 0)
        for status, count in db.execute('SELECT status,count(*) FROM examples GROUP BY status'):
            summary[status.lower()] = count
        summary['rejected'] += batch['invalid_rows']
        report = {'schema_version': SCHEMA_VERSION, 'totals': summary,
                  'batch': {'upserted': batch['upserted'], 'invalid_rows': batch['invalid_rows']},
                  'input': 'offline-jsonl', 'publishable': summary['accepted'],
                  'note': 'Invalid lines are rejected with non-content diagnostics; review records are never published.'}
        (out_dir / 'report.json').write_text(canonical(report) + '\n', encoding='utf-8')
        return report


def search(db_path, language, situation=None, sense_id=None, limit=25, statuses=('ACCEPTED',)):
    if not LANG.fullmatch(language) or type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError('invalid retrieval arguments')
    if not statuses or any(s not in ('ACCEPTED', 'REQUIRES_REVIEW', 'REJECTED') for s in statuses):
        raise ValueError('invalid retrieval status')
    clauses = ['e.language=?', 'e.status IN (' + ','.join('?' for _ in statuses) + ')']
    params = [language, *statuses]
    if situation:
        clauses.append('e.situation=?')
        params.append(situation)
    if sense_id:
        clauses.append('EXISTS(SELECT 1 FROM example_senses s WHERE s.id=e.id AND s.sense_id=?)')
        params.append(sense_id)
    query = 'SELECT e.export_json FROM examples e WHERE ' + ' AND '.join(clauses) + ' ORDER BY e.id LIMIT ?'
    with sqlite3.connect('file:' + str(Path(db_path).resolve()) + '?mode=ro', uri=True) as db:
        return [json.loads(item[0]) for item in db.execute(query, (*params, limit))]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    a = sub.add_parser('ingest', help='incremental offline JSONL ingestion')
    for flag in ('input', 'db', 'out'):
        a.add_argument('--' + flag, required=True, type=Path)
    for flag in ('ledger', 'senses', 'rules', 'reviewers'):
        a.add_argument('--' + flag, type=Path)
    q = sub.add_parser('search', help='indexed, bounded retrieval')
    q.add_argument('--db', required=True, type=Path)
    q.add_argument('--language', required=True)
    q.add_argument('--situation')
    q.add_argument('--sense')
    q.add_argument('--limit', type=int, default=25)
    opts = parser.parse_args(argv)
    if opts.command == 'ingest':
        result = ingest(opts.input, opts.db, opts.out, opts.ledger, opts.senses, opts.rules, opts.reviewers)
    else:
        result = search(opts.db, opts.language, opts.situation, opts.sense, opts.limit)
    print(canonical(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
