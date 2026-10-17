"""Opt-in bounded admission entry point; never grants legal/source approval.

Run with python -m tools.gha_factory.admission.verified_snapshot. Existing
pipeline/workflows remain owned by PR #178 and are not redirected by this patch.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from urllib.parse import parse_qs, urlsplit

from legal.ledger.license_notice import (
    ALWAYS_CONFLICT, conflicting_license_ids, detected_licenses, read_notice,
)
from . import pipeline

_DECISION_PREFIX = '/moaz76943-creator/-offline-packs-store/'
_DECISION_PATH = re.compile(r'(?:issues|pull)/\d+/?\Z')

MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_PROOF_BYTES = 1024 * 1024


def copy_snapshot(root, relative, destination, expected=None, limit=MAX_PROOF_BYTES,
                  jsonl=False):
    """Pin regular-file bytes in an isolated snapshot before parsing/hashing them."""
    if not isinstance(relative, str) or not relative:
        raise pipeline.AdmissionError('BLOCKED_SOURCE: missing snapshot path')
    parts = Path(relative).parts
    if Path(relative).is_absolute() or any(p in ('..', '.git') for p in parts):
        raise pipeline.AdmissionError('BLOCKED_SOURCE: unsafe snapshot path')
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise pipeline.AdmissionError('BLOCKED_SOURCE: symlink snapshot')
    if expected is not None and (not isinstance(expected, str) or not pipeline.SHA.fullmatch(expected)):
        raise pipeline.AdmissionError('BLOCKED_SOURCE: invalid snapshot SHA256')
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise pipeline.AdmissionError('BLOCKED_SOURCE: snapshot type/size limit')
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            total = 0
            with destination.open('xb') as out:
                while True:
                    chunk = stream.readline(pipeline.MAX_LINE + 1) if jsonl else stream.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > limit or (jsonl and (len(chunk) > pipeline.MAX_LINE or not chunk.endswith(b'\n'))):
                        raise pipeline.AdmissionError('BLOCKED_SOURCE: snapshot byte/line limit')
                    digest.update(chunk)
                    out.write(chunk)
            if expected is not None and digest.hexdigest() != expected:
                raise pipeline.AdmissionError('BLOCKED_SOURCE: snapshot SHA256 mismatch')
    except OSError as exc:
        raise pipeline.AdmissionError('BLOCKED_SOURCE: snapshot unavailable') from exc


def repo_decision_url(value):
    """Owner decision links must be an issue or pull request on this repository."""
    if not isinstance(value, str) or not value:
        return False
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    forbidden = {'token', 'key', 'access_token', 'signature', 'auth', 'password'}
    return (parts.scheme == 'https' and parts.hostname == 'github.com'
            and not parts.username and not parts.password
            and not (set(parse_qs(parts.query)) & forbidden)
            and parts.path.startswith(_DECISION_PREFIX)
            and bool(_DECISION_PATH.fullmatch(parts.path[len(_DECISION_PREFIX):])))


def license_notice(path, license_id, co_offered=()):
    """Shared-scanner check only; text recognition is NOT a legal decision."""
    notice = read_notice(path)
    if notice is None:
        raise pipeline.AdmissionError('BLOCKED_SOURCE: unreadable rights snapshot')
    detected = detected_licenses(notice)
    conflicts = conflicting_license_ids(detected, license_id, co_offered)
    if conflicts & ALWAYS_CONFLICT:
        raise pipeline.AdmissionError('BLOCKED_SOURCE: conflicting restricted rights notice')
    if conflicts:
        raise pipeline.AdmissionError('BLOCKED_SOURCE: license metadata/notice conflict')
    if license_id not in detected:
        raise pipeline.AdmissionError('BLOCKED_SOURCE: rights notice requires independent reconciliation')


def admit_verified(*, repo_root, source_id, input_path, out_dir, language,
                   dataset_version, part_size=1000):
    root = Path(repo_root).resolve()
    if not isinstance(source_id, str) or not pipeline.ID.fullmatch(source_id):
        raise pipeline.AdmissionError('BLOCKED_SOURCE: invalid source ID')
    try:
        with tempfile.TemporaryDirectory(prefix='verified-admission-') as temporary:
            pinned = Path(temporary)
            ledger_path = pinned / 'legal/ledger/sources.json'
            copy_snapshot(root, 'legal/ledger/sources.json', ledger_path)
            ledger = json.loads(ledger_path.read_text(encoding='utf-8'))
            if not isinstance(ledger, dict) or ledger.get('schema_version') != pipeline.SOURCE_SCHEMA or not isinstance(ledger.get('sources'), list):
                raise pipeline.AdmissionError('BLOCKED_SOURCE: invalid ledger')
            matches = [s for s in ledger['sources'] if isinstance(s, dict) and s.get('source_id') == source_id]
            if len(matches) != 1 or matches[0].get('status') != 'APPROVED_FOR_REDISTRIBUTION':
                raise pipeline.AdmissionError('BLOCKED_SOURCE: independent source approval absent')
            source = matches[0]
            retrieval, rights, review = (source.get(k) for k in ('retrieval', 'license', 'review'))
            if not all(isinstance(v, dict) for v in (retrieval, rights, review)):
                raise pipeline.AdmissionError('BLOCKED_SOURCE: malformed evidence metadata')
            if not repo_decision_url(review.get('decision_url')):
                raise pipeline.AdmissionError(
                    'BLOCKED_SOURCE: reviewer decision must link to this repository')
            # Companion descriptor preserves the existing strict ledger schema.
            descriptor_path = pinned / 'review-snapshot.json'
            copy_snapshot(root, f'legal/ledger/review_snapshots/{source_id}.json', descriptor_path)
            descriptor = json.loads(descriptor_path.read_text(encoding='utf-8'))
            bindings = {'source_id': source_id, 'dataset_version': dataset_version,
                        'source_sha256': retrieval.get('sha256'),
                        'license_evidence_sha256': rights.get('evidence_sha256'),
                        'reviewer': review.get('reviewer'), 'decision_url': review.get('decision_url')}
            if not isinstance(descriptor, dict) or any(descriptor.get(k) != v for k, v in bindings.items()):
                raise pipeline.AdmissionError('BLOCKED_SOURCE: reviewer snapshot binding mismatch')
            # Require actual decision evidence, not just a contributor-supplied URL.
            for section, path_key, hash_key, bound, lines in (
                (descriptor, 'evidence_path', 'evidence_sha256', MAX_PROOF_BYTES, False),
                (rights, 'evidence_path', 'evidence_sha256', MAX_PROOF_BYTES, False),
                (retrieval, 'artifact_path', 'sha256', MAX_SOURCE_BYTES, True),
            ):
                expected = section.get(hash_key)
                if not isinstance(expected, str) or not pipeline.SHA.fullmatch(expected):
                    raise pipeline.AdmissionError('BLOCKED_SOURCE: missing evidence SHA256')
                relative = section.get(path_key)
                if not isinstance(relative, str):
                    raise pipeline.AdmissionError('BLOCKED_SOURCE: missing evidence path')
                copy_snapshot(root, relative, pinned / relative, expected, bound, lines)
            reviewed_input = (root / retrieval['artifact_path']).resolve()
            if Path(input_path).resolve() != reviewed_input:
                raise pipeline.AdmissionError('BLOCKED_SOURCE: input differs from reviewed snapshot')
            license_notice(
                pinned / rights['evidence_path'], rights.get('id'),
                rights.get('co_offered_licenses', ()))
            copy_snapshot(root, 'catalog/language_registry.v1.json', pinned / 'catalog/language_registry.v1.json')
            # Only selected source is exposed to the legacy adapter; pinned bytes
            # prevent source/ledger changes between preflight and partitioning.
            ledger_path.write_bytes(pipeline.canon({'schema_version': pipeline.SOURCE_SCHEMA, 'sources': [source]}))
            return pipeline.admit(repo_root=pinned, source_id=source_id,
                                  input_path=pinned / retrieval['artifact_path'],
                                  out_dir=out_dir, language=language,
                                  dataset_version=dataset_version, part_size=part_size)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, pipeline.AdmissionError):
            raise
        raise pipeline.AdmissionError('BLOCKED_SOURCE: invalid/unavailable snapshot evidence') from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path.cwd())
    parser.add_argument('--ledger-source-id', required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--language', required=True)
    parser.add_argument('--dataset-version', required=True)
    parser.add_argument('--part-size', type=int, default=1000)
    args = parser.parse_args(argv)
    try:
        result = admit_verified(repo_root=args.repo_root, source_id=args.ledger_source_id,
                                input_path=args.input, out_dir=args.out, language=args.language,
                                dataset_version=args.dataset_version, part_size=args.part_size)
    except pipeline.AdmissionError as exc:
        print(str(exc))
        return 2
    print(json.dumps({k: v for k, v in result.items() if k != 'jobs'}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
