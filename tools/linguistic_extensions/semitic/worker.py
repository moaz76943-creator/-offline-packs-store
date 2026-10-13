#!/usr/bin/env python3
"""Offline, bounded, restartable verified-source JSONL worker (stdlib only).

The ledger's specific morphology source snapshot is the ONLY eligible input.
Output is candidate evidence, never an approved/published language pack.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

try:
    from .contract import ContractError, strict_json, load_profile, validate_candidate, MAX_LINE
except ImportError:  # support direct command as well as python -m
    from contract import ContractError, strict_json, load_profile, validate_candidate, MAX_LINE

MAX_SHARD_BYTES = 250_000_000
CHECKPOINT_KEYS = {'schema_version', 'language', 'source_id', 'dataset_version',
                   'source_sha256', 'next_line', 'total_accepted', 'segment_count',
                   'segment_sha256', 'complete', 'run_id'}


def _sha_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(65536), b''):
            digest.update(block)
    return digest.hexdigest()


def _safe_file(root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ContractError('missing or unsafe source path')
    base = root.resolve()
    path = (base / relative).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise ContractError('missing source or symlink escape')
    return path


def _url(value):
    if not isinstance(value, str):
        return False
    parts = urlsplit(value)
    return parts.scheme == 'https' and bool(parts.hostname) and not parts.username and not parts.password


def approved_snapshot(root, language, source_id):
    """Fail-closed source-specific Route 05 checks; cannot grant legal approval.

    A later release still needs the canonical ledger admission and release gate.
    """
    load_profile(root, language)
    ledger = strict_json((root / 'legal/ledger/sources.json').read_bytes())
    if ledger.get('schema_version') != '1.0.0' or not isinstance(ledger.get('sources'), list):
        raise ContractError('unsupported source ledger')
    matches = [x for x in ledger['sources'] if x.get('source_id') == source_id]
    if len(matches) != 1:
        raise ContractError('BLOCKED_SOURCE: source is not in canonical approved ledger')
    source = matches[0]
    if source.get('status') != 'APPROVED_FOR_REDISTRIBUTION' or source.get('kind') != 'morphology':
        raise ContractError('BLOCKED_SOURCE: source is not approved morphology')
    review = source.get('review') or {}
    retrieval = source.get('retrieval') or {}
    lic = source.get('license') or {}
    if (not isinstance(source.get('dataset_version'), str) or not source['dataset_version'] or
            not isinstance(source.get('publisher'), str) or not source['publisher'].strip() or
            not _url(source.get('origin_url')) or not _url(retrieval.get('url')) or
            not isinstance(retrieval.get('identity'), str) or not retrieval['identity'] or
            not isinstance(retrieval.get('date'), str) or
            not isinstance(review.get('reviewer'), str) or not review['reviewer'] or
            not _url(review.get('decision_url')) or
            lic.get('id') not in ('CC-BY-SA-4.0', 'GFDL-1.3-only', 'CC0-1.0', 'PUBLIC-DOMAIN') or
            not _url(lic.get('evidence_url')) or 'creativecommons.org/licenses/' in lic['evidence_url'] or
            'gnu.org/licenses/fdl-' in lic['evidence_url'] or
            not isinstance(source.get('alterations'), list) or not source['alterations']):
        raise ContractError('BLOCKED_SOURCE: incomplete source-specific legal evidence')
    if lic['id'] == 'PUBLIC-DOMAIN' and not all(
            (lic.get('public_domain_proof') or {}).get(k) for k in ('jurisdiction','legal_basis','work_date')):
        raise ContractError('BLOCKED_SOURCE: missing public-domain proof')
    for relative, sha in ((retrieval.get('artifact_path'), retrieval.get('sha256')),
                          (lic.get('evidence_path'), lic.get('evidence_sha256'))):
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ContractError('BLOCKED_SOURCE: missing verified SHA-256')
        path = _safe_file(root, relative)
        if path.stat().st_size > MAX_SHARD_BYTES or _sha_file(path) != sha:
            raise ContractError('BLOCKED_SOURCE: changed, oversized or unverified source')
    return source, _safe_file(root, retrieval['artifact_path'])


def resume_checkpoint(directory, language, source_id, source, expected_run_id=None):
    if directory is None:
        return 0, 0
    directory = Path(directory)
    checkpoint = strict_json((directory / 'checkpoint.json').read_bytes())
    if not isinstance(checkpoint, dict) or set(checkpoint) != CHECKPOINT_KEYS:
        raise ContractError('invalid resume checkpoint fields')
    if expected_run_id is not None and checkpoint.get('run_id') != str(expected_run_id):
        raise ContractError('wrong previous workflow run ID')
    if (checkpoint['schema_version'] != '1.0.0' or checkpoint['language'] != language or
            checkpoint['source_id'] != source_id or
            checkpoint['dataset_version'] != source['dataset_version'] or
            checkpoint['source_sha256'] != source['retrieval']['sha256'] or
            type(checkpoint['next_line']) is not int or checkpoint['next_line'] < 0 or
            type(checkpoint['total_accepted']) is not int or checkpoint['total_accepted'] < 0 or
            type(checkpoint['segment_count']) is not int or checkpoint['segment_count'] < 0 or
            type(checkpoint['complete']) is not bool or checkpoint['complete'] or
            not isinstance(checkpoint['segment_sha256'], str) or
            not isinstance(checkpoint['run_id'], str) or not checkpoint['run_id']):
        raise ContractError('stale or incompatible resume checkpoint')
    output = directory / 'accepted.jsonl'
    if not output.is_file() or _sha_file(output) != checkpoint['segment_sha256']:
        raise ContractError('resume candidate segment hash mismatch')
    with output.open('rb') as handle:
        actual_count = 0
        for line in handle:
            if not line.endswith(b'\n') or len(line) > MAX_LINE:
                raise ContractError('damaged resume segment')
            actual_count += 1
    if actual_count != checkpoint['segment_count'] or checkpoint['total_accepted'] < actual_count:
        raise ContractError('resume segment count mismatch')
    return checkpoint['next_line'], checkpoint['total_accepted']


def process(root, language, source_id, out_dir, max_records=5000, resume_dir=None, run_id='local', resume_run_id=None):
    root = Path(root).resolve()
    if type(max_records) is not int or not 1 <= max_records <= 10000:
        raise ContractError('max_records must be 1..10000')
    if not isinstance(run_id, str) or not run_id:
        raise ContractError('run ID required')
    source, artifact = approved_snapshot(root, language, source_id)
    if artifact.suffix != '.jsonl':
        raise ContractError('approved shard must be JSONL; no implicit parser guesses')
    start, cumulative = resume_checkpoint(resume_dir, language, source_id, source, resume_run_id)
    out_dir = Path(out_dir).resolve()
    if out_dir == root or artifact.is_relative_to(out_dir) or (resume_dir and out_dir == Path(resume_dir).resolve()):
        raise ContractError('unsafe output directory')
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in (out_dir / 'accepted.jsonl', out_dir / 'checkpoint.json'):
        if path.exists():
            raise ContractError('refusing to overwrite previous checkpoint')
    tmp = out_dir / 'accepted.jsonl.tmp'
    complete = True
    count = 0
    last_line = 0
    next_line = start
    digest = hashlib.sha256()
    try:
        with artifact.open('rb') as source_file, tmp.open('xb') as output:
            for line_no, raw in enumerate(source_file, 1):
                last_line = line_no
                if line_no <= start:
                    continue
                if count >= max_records:
                    complete = False
                    break
                if len(raw) > MAX_LINE or not raw.endswith(b'\n') or not raw.strip():
                    raise ContractError('corrupted or oversized JSONL at line ' + str(line_no))
                item = strict_json(raw)
                # The verified shard cannot embed its own SHA-256 (circular hash).
                # Bind the validated artifact digest only AFTER checking the ledger.
                if not isinstance(item, dict) or not isinstance(item.get('evidence'), dict) or 'source_sha256' in item['evidence']:
                    raise ContractError('source shard must not self-assert source SHA-256')
                item['evidence']['source_sha256'] = source['retrieval']['sha256']
                validate_candidate(item, root, language, source_id,
                                   source['dataset_version'], source['retrieval']['sha256'])
                encoded = (json.dumps(item, ensure_ascii=False, sort_keys=True,
                                      separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
                output.write(encoded)
                digest.update(encoded)
                count += 1
                next_line = line_no
        if start > last_line:
            raise ContractError('checkpoint exceeds verified source line count')
        checkpoint = {
            'schema_version': '1.0.0', 'language': language, 'source_id': source_id,
            'dataset_version': source['dataset_version'],
            'source_sha256': source['retrieval']['sha256'],
            'next_line': next_line, 'total_accepted': cumulative + count,
            'segment_count': count, 'segment_sha256': digest.hexdigest(),
            'complete': complete, 'run_id': run_id,
        }
        tmp.replace(out_dir / 'accepted.jsonl')
        (out_dir / 'checkpoint.json').write_text(
            json.dumps(checkpoint, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')
        return checkpoint
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def coverage(root):
    """Exact current approved production-source and standard pilot form counts."""
    root = Path(root)
    ledger = strict_json((root / 'legal/ledger/sources.json').read_bytes())
    pilot = {'ar': 0, 'am': 0}
    forms = root / 'standards/morphology/attested_forms.jsonl'
    if forms.is_file():
        with forms.open('rb') as handle:
            for raw in handle:
                if raw.strip():
                    record = strict_json(raw)
                    if record.get('language_code') in pilot:
                        pilot[record['language_code']] += 1
    approved = sorted(s['source_id'] for s in ledger.get('sources', [])
                      if isinstance(s, dict) and s.get('status') == 'APPROVED_FOR_REDISTRIBUTION'
                      and s.get('kind') == 'morphology')
    return {'schema_version': '1.0.0', 'baseline_pilot_attestations': pilot,
            'approved_morphology_sources': approved, 'accepted_production_forms': {'ar': 0, 'am': 0},
            'note': 'Accepted production count is zero until a source-backed shard run produces a verified checkpoint; pilot forms are NOT redistribution approvals.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('coverage','shard'))
    parser.add_argument('--repo-root', default='.')
    parser.add_argument('--language', choices=('ar','am'))
    parser.add_argument('--source-id')
    parser.add_argument('--out-dir')
    parser.add_argument('--resume-dir')
    parser.add_argument('--resume-run-id')
    parser.add_argument('--max-records', type=int, default=5000)
    parser.add_argument('--run-id', default=os.environ.get('GITHUB_RUN_ID', 'local'))
    args = parser.parse_args()
    try:
        if args.mode == 'coverage':
            result = coverage(args.repo_root)
        else:
            if not args.language or not args.source_id or not args.out_dir:
                parser.error('shard requires --language, --source-id and --out-dir')
            result = process(args.repo_root, args.language, args.source_id,
                             args.out_dir, args.max_records, args.resume_dir, args.run_id, args.resume_run_id)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except (ContractError, OSError, KeyError, TypeError) as exc:
        parser.exit(3, 'BLOCKED_EVIDENCE: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
