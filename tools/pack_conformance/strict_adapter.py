#!/usr/bin/env python3
"""Bounded, fail-closed adapter to canonical public SQLite v2 pack conformance.

Never interprets a fixture, metadata-only proof, or a zero-job event as release.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import zlib

MAX_ARCHIVE=40*1024*1024
MAX_ENVELOPE=120*1024*1024
SHA=re.compile(r'^[a-f0-9]{64}$')

class QARejected(ValueError):
    pass


def confined(root,relative):
    if not isinstance(relative,str) or not relative or '\\' in relative:
        raise QARejected('unsafe candidate path')
    p=Path(relative)
    if p.is_absolute() or '..' in p.parts or '.git' in p.parts:
        raise QARejected('unsafe candidate path')
    cur=root
    for part in p.parts:
        cur=cur/part
        if cur.is_symlink():raise QARejected('symlink candidate path')
    if not cur.resolve().is_relative_to(root) or not cur.is_file():
        raise QARejected('missing candidate file')
    return cur


def safe_archive(blob):
    if not blob.startswith(b'\x1f\x8b') or len(blob)>MAX_ARCHIVE:
        raise QARejected('invalid compressed candidate')
    dec=zlib.decompressobj(16+zlib.MAX_WBITS)
    try: out=dec.decompress(blob,MAX_ENVELOPE+1)
    except zlib.error as exc:raise QARejected('malformed compressed candidate') from exc
    if len(out)>MAX_ENVELOPE:
        raise QARejected('candidate gzip decompression limit')
    if not dec.eof or dec.unconsumed_tail or dec.unused_data:
        raise QARejected('truncated or trailing candidate gzip')


def inspect_candidate(root,path,language,sha256):
    root=Path(root).resolve()
    if not isinstance(sha256,str) or not SHA.fullmatch(sha256):
        raise QARejected('expected SHA-256 required')
    if not isinstance(language,str) or not re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z0-9]+)*',language):
        raise QARejected('invalid language identity')
    candidate=confined(root,path)
    if candidate.stat().st_size>MAX_ARCHIVE:
        raise QARejected('candidate byte limit')
    blob=candidate.read_bytes()
    if hashlib.sha256(blob).hexdigest()!=sha256:
        raise QARejected('independent archive SHA-256 mismatch')
    safe_archive(blob)
    from tools.gha_factory.pack_conformance.check import inspect as canonical_inspect
    report=canonical_inspect(blob,language,root=root,allow_fixture=False,expected_sha256=sha256)
    if (report.get('fixture_only') is not False
            or report.get('archive_sha256')!=sha256
            or not report.get('sqlite_sha256')
            or type(report.get('actual_lexical_count')) is not int
            or report['actual_lexical_count']<=0
            or not isinstance(report.get('source_ids'),list)
            or not report['source_ids']):
        raise QARejected('incomplete, synthetic or self-inconsistent canonical QA report')
    if hashlib.sha256(candidate.read_bytes()).hexdigest()!=sha256:
        raise QARejected('candidate mutated during QA')
    return {'status':'QA_QUARANTINED_PENDING_RELEASE_GATE',
            'language':language,'archive_sha256':sha256,
            'sqlite_sha256':report['sqlite_sha256'],
            'actual_lexical_count':report['actual_lexical_count'],
            'source_ids':sorted(report['source_ids']),
            'schema_version':report.get('schema_version'),
            'signature_verified':False,'hosted_jobs_verified':False,
            'publication_approved':False}


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo-root',type=Path,required=True)
    ap.add_argument('--archive',required=True)
    ap.add_argument('--language',required=True)
    ap.add_argument('--sha256',required=True)
    args=ap.parse_args(argv)
    try:
        print(json.dumps(inspect_candidate(args.repo_root,args.archive,args.language,args.sha256),sort_keys=True))
        return 0
    except (QARejected,ValueError,KeyError,TypeError,ImportError,OSError) as exc:
        print(json.dumps({'status':'BLOCKED','reason':str(exc),'publication_approved':False},sort_keys=True))
        return 2

if __name__=='__main__':sys.exit(main())
