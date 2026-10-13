#!/usr/bin/env python3
"""Offline, non-publishing handoff for a source-verified SQLite v2 candidate.

Only canonical Route 05/07/13 validators can establish admissibility. A handoff
is not a publication authorization. Existing handoffs are immutable.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

SHA = re.compile(r'^[0-9a-f]{64}$')
MAX_JSON = 2 * 1024 * 1024
MAX_PACK = 40 * 1024 * 1024

class Blocked(ValueError):
    pass


def canonical_json(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def strict_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON:
        raise Blocked('missing, symlinked or oversized evidence JSON')
    def distinct(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Blocked('duplicate JSON evidence key')
            result[key] = value
        return result
    try:
        return json.loads(path.read_bytes().decode('utf-8'),
                          object_pairs_hook=distinct,
                          parse_constant=lambda _: (_ for _ in ()).throw(Blocked('nonfinite JSON')))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise Blocked('invalid evidence JSON') from exc


def local_file(root, name):
    if not isinstance(name, str) or not name or '\\' in name:
        raise Blocked('unsafe relative artifact path')
    rel = Path(name)
    if rel.is_absolute() or '..' in rel.parts or '.git' in rel.parts:
        raise Blocked('unsafe relative artifact path')
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise Blocked('symlinked artifact component')
    resolved = current.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise Blocked('missing or escaping artifact')
    return resolved


def sha256_file(path, limit):
    if path.stat().st_size > limit:
        raise Blocked('artifact byte limit')
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(65536), b''):
            h.update(block)
    return h.hexdigest()


def release_evidence(root, path, expected_sha, language):
    """Independent proof AND exact source-admission mapping, never caller approval."""
    if not isinstance(expected_sha, str) or not SHA.fullmatch(expected_sha):
        raise Blocked('invalid expected archive SHA-256')
    archive = local_file(root, path)
    if sha256_file(archive, MAX_PACK) != expected_sha:
        raise Blocked('archive SHA-256 mismatch')
    ledger = strict_json(root / 'legal/ledger/sources.json')
    manifest = strict_json(root / 'manifest.json')
    if not isinstance(ledger, dict) or not isinstance(manifest, dict):
        raise Blocked('ledger/manifest must be JSON objects')
    daily_dir = root / 'legal/ledger/daily'
    if not daily_dir.is_dir() or daily_dir.is_symlink():
        raise Blocked('missing daily admission records')
    dailies = [strict_json(p) for p in sorted(daily_dir.glob('*.json'))]
    from legal.ledger.admission import evaluate
    blockers = evaluate(ledger, manifest, dailies, root)
    if blockers:
        raise Blocked('rights admission rejected: ' + '; '.join(blockers[:4]))
    if manifest.get('intellectual_property_status') == 'UNVERIFIED_RIGHTS':
        raise Blocked('top-level rights remain UNVERIFIED_RIGHTS')
    candidates = [item for daily in dailies if isinstance(daily, dict)
                  for item in daily.get('release_candidates', []) if isinstance(item, dict)
                  and item.get('artifact_path') == path and item.get('sha256') == expected_sha]
    if len(candidates) != 1 or candidates[0].get('kind') != 'dictionary':
        raise Blocked('no unique independently admitted dictionary candidate')
    if candidates[0].get('language_code') != language:
        raise Blocked('candidate language identity missing or mismatched')
    from tools.gha_factory.pack_conformance.check import inspect
    result = inspect(archive.read_bytes(), language, root=root,
                     allow_fixture=False, expected_sha256=expected_sha)
    if result.get('fixture_only') or result.get('actual_lexical_count', 0) <= 0:
        raise Blocked('fixture or empty candidate is not production evidence')
    return {'schema_version': '1.0.0', 'status': 'QUARANTINED_PENDING_RELEASE_APPROVAL',
            'language': language, 'artifact_path': path, 'archive_sha256': expected_sha,
            'sqlite_sha256': result['sqlite_sha256'],
            'actual_lexical_count': result['actual_lexical_count'],
            'conformance_version': result['conformance_version'],
            'rights_admission': 'PASSED_REVIEW_EVIDENCE',
            'signature_verified': False, 'publication_approved': False,
            'claimed_jobs_verified': False, 'corpus_processing_succeeded': False}


def write_handoff(root, evidence):
    """No overwrite, deterministic bytes, hard-link based exclusive creation."""
    if not SHA.fullmatch(str(evidence.get('archive_sha256', ''))):
        raise Blocked('invalid handoff archive hash')
    if evidence.get('publication_approved') is not False:
        raise Blocked('handoff cannot authorize publication')
    outdir = root / 'tools/release_validation/handoffs'
    if outdir.is_symlink():
        raise Blocked('unsafe handoff directory')
    outdir.mkdir(parents=True, exist_ok=True)
    if outdir.resolve() != outdir.absolute():
        raise Blocked('handoff directory escapes repository')
    destination = outdir / (evidence['archive_sha256'] + '.json')
    raw = canonical_json(evidence)
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_file() or destination.read_bytes() != raw:
            raise Blocked('immutable handoff collision')
        return destination
    fd, temporary = tempfile.mkstemp(dir=outdir, prefix='.handoff-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.is_symlink() or destination.read_bytes() != raw:
                raise Blocked('concurrent immutable handoff collision')
        directory_fd = os.open(outdir, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, required=True)
    parser.add_argument('--candidate', required=True, help='repository-relative archive path')
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--language', required=True)
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    try:
        result = release_evidence(root, args.candidate, args.sha256, args.language)
        output = write_handoff(root, result)
        print(canonical_json({'status': result['status'], 'handoff': str(output),
                              'publication_approved': False}).decode(), end='')
        return 0
    except (Blocked, OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        print(canonical_json({'status': 'BLOCKED', 'reason': str(exc),
                              'publication_approved': False}).decode(), end='')
        return 2


if __name__ == '__main__':
    sys.exit(main())
