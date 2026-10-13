#!/usr/bin/env python3
"""Source-hash and Route-05-evidence circuit breaker (NON-INTEGRATING).

An admitted source is not proof that its content was ingested or published.
Integration remains prohibited until the coordinator links this gate to a
specific transaction, which is outside this module's ownership scope.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

SHA = re.compile(r'^[a-f0-9]{64}$')
MAX_SOURCE = 20 * 1024 * 1024
MAX_JSON = 2 * 1024 * 1024

class GateBlocked(ValueError):
    pass


def strictly_read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON:
        raise GateBlocked('missing, symlinked or oversized admission JSON')
    def distinct(pairs):
        obj = {}
        for k, v in pairs:
            if k in obj:
                raise GateBlocked('duplicate admission JSON property')
            obj[k] = v
        return obj
    try:
        return json.loads(path.read_bytes().decode('utf-8'), object_pairs_hook=distinct,
                          parse_constant=lambda _: (_ for _ in ()).throw(GateBlocked('nonfinite JSON number')))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise GateBlocked('malformed admission JSON') from exc


def safe_source(root, relative):
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise GateBlocked('unsafe source path')
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or '.git' in rel.parts:
        raise GateBlocked('unsafe source path')
    cur = root
    for part in rel.parts:
        cur = cur / part
        if cur.is_symlink():
            raise GateBlocked('symlinked source path')
    if not cur.resolve().is_relative_to(root) or not cur.is_file():
        raise GateBlocked('missing source snapshot')
    return cur


def sha256_bounded(path):
    if path.stat().st_size > MAX_SOURCE:
        raise GateBlocked('source exceeds maximum bytes')
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def admit(root, source_path, source_id, expected_sha, *, integrate=False):
    root = Path(root).resolve()
    if (not isinstance(source_id, str) or not source_id.strip()
            or not isinstance(expected_sha,str) or not SHA.fullmatch(expected_sha)):
        raise GateBlocked('source ID and expected SHA-256 required')
    snapshot = safe_source(root, source_path)
    if sha256_bounded(snapshot) != expected_sha:
        raise GateBlocked('source bytes differ from expected SHA-256')
    ledger = strictly_read(root/'legal/ledger/sources.json')
    manifest = strictly_read(root/'manifest.json')
    daily_dir = root/'legal/ledger/daily'
    if daily_dir.is_symlink() or not daily_dir.is_dir():
        raise GateBlocked('missing daily license evidence')
    dailies = [strictly_read(p) for p in sorted(daily_dir.glob('*.json'))]
    if not isinstance(ledger,dict) or not isinstance(ledger.get('sources'),list):
        raise GateBlocked('invalid public source ledger')
    matches = [src for src in ledger['sources']
               if isinstance(src,dict) and src.get('source_id') == source_id]
    if len(matches) != 1:
        raise GateBlocked('source ID not uniquely recorded in approved ledger')
    source = matches[0]
    retrieval = source.get('retrieval')
    if (source.get('status') != 'APPROVED_FOR_REDISTRIBUTION'
            or not isinstance(retrieval,dict)
            or retrieval.get('artifact_path') != source_path
            or retrieval.get('sha256') != expected_sha
            or not isinstance(source.get('license'),dict)
            or not isinstance(source['license'].get('id'),str)
            or not isinstance(source.get('review'),dict)):
        raise GateBlocked('source identity, version, provenance or rights not independently approved')
    from legal.ledger.admission import evaluate
    blockers = evaluate(ledger,manifest,dailies,root)
    if blockers:
        raise GateBlocked('canonical rights admission blocked: ' + '; '.join(blockers[:3]))
    if integrate:
        raise GateBlocked('BLOCKED_INTEGRATION: no coordinator-enforced transaction exists')
    return {'status':'QUARANTINED_PENDING_COORDINATOR',
            'source_id':source_id,'source_sha256':expected_sha,
            'dataset_version':source.get('dataset_version'),
            'license_id':source['license']['id'],
            'rights_evidence_audited':True, 'integrated':False,
            'claimed_jobs_verified':False, 'corpus_processing_succeeded':False,
            'publication_approved':False}


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo-root',type=Path,required=True)
    ap.add_argument('--source',required=True,help='repository-relative source snapshot')
    ap.add_argument('--source-id',required=True)
    ap.add_argument('--sha256',required=True)
    ap.add_argument('--integrate',action='store_true')
    args=ap.parse_args(argv)
    try:
        report=admit(args.repo_root,args.source,args.source_id,args.sha256,integrate=args.integrate)
        print(json.dumps(report,sort_keys=True))
        return 0
    except (GateBlocked, OSError, TypeError, KeyError, ImportError) as exc:
        print(json.dumps({'status':'BLOCKED','reason':str(exc),
                          'integrated':False,'publication_approved':False},sort_keys=True))
        return 2

if __name__ == '__main__':
    sys.exit(main())
