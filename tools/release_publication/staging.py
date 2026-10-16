#!/usr/bin/env python3
"""Deterministic, local-only SQLite v2 staging. Publication is not supported.

No advertised public-domain claim or caller credential authorizes a release.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tarfile
import tempfile
import zlib

SHA=re.compile(r'^[a-f0-9]{64}$')
MAX_ARCHIVE=40*1024*1024
MAX_ENVELOPE=120*1024*1024

class StageBlocked(ValueError):
    pass


def source_file(root,rel):
    if not isinstance(rel,str) or not rel or '\\' in rel:
        raise StageBlocked('unsafe pack path')
    p=Path(rel)
    if p.is_absolute() or '..' in p.parts or '.git' in p.parts:
        raise StageBlocked('unsafe pack path')
    cur=root
    for part in p.parts:
        cur=cur/part
        if cur.is_symlink():raise StageBlocked('symlinked pack path')
    if not cur.resolve().is_relative_to(root) or not cur.is_file():
        raise StageBlocked('missing pack bytes')
    return cur


def bounded_gzip(blob):
    if not blob.startswith(b'\x1f\x8b') or len(blob)>MAX_ARCHIVE:
        raise StageBlocked('invalid or oversized pack gzip')
    dec=zlib.decompressobj(16+zlib.MAX_WBITS)
    try: content=dec.decompress(blob,MAX_ENVELOPE+1)
    except zlib.error as exc:raise StageBlocked('corrupt pack gzip') from exc
    if len(content)>MAX_ENVELOPE:
        raise StageBlocked('pack gzip expansion limit exceeded')
    if not dec.eof or dec.unused_data or dec.unconsumed_tail:
        raise StageBlocked('invalid or trailing pack gzip data')
    return True


def stage_bytes(root,relative,language,expected_sha):
    root=Path(root).resolve()
    if (not isinstance(language,str) or not re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z0-9]+)*',language)
            or not isinstance(expected_sha,str) or not SHA.fullmatch(expected_sha)):
        raise StageBlocked('invalid release identity')
    path=source_file(root,relative)
    if path.stat().st_size>MAX_ARCHIVE:
        raise StageBlocked('pack too large')
    blob=path.read_bytes()
    if hashlib.sha256(blob).hexdigest()!=expected_sha:
        raise StageBlocked('independently verified archive SHA-256 mismatch')
    bounded_gzip(blob)
    from tools.gha_factory.pack_conformance.check import inspect
    result=inspect(blob,language,root=root,allow_fixture=False,expected_sha256=expected_sha)
    if result.get('fixture_only') or result.get('publication_approved') is True:
        raise StageBlocked('fixture or invalid self-publishing evidence')
    if result.get('archive_sha256')!=expected_sha or not result.get('source_ids'):
        raise StageBlocked('conformance archive/source identity mismatch')
    if not isinstance(result.get('sqlite_sha256'),str) or not SHA.fullmatch(result['sqlite_sha256']):
        raise StageBlocked('missing verified SQLite SHA-256')
    receipt={'stage_version':'1.0.0','language':language,'pack_archive_sha256':expected_sha,
             'sqlite_sha256':result['sqlite_sha256'],'source_ids':sorted(result['source_ids']),
             'status':'STAGED_PENDING_FINAL_RELEASE_GATES',
             'signature_verified':False,'publication_approved':False}
    meta=(json.dumps(receipt,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
    stream=io.BytesIO()
    with gzip.GzipFile(filename='',mode='wb',mtime=0,fileobj=stream,compresslevel=9) as zipped:
        with tarfile.open(fileobj=zipped,mode='w',format=tarfile.USTAR_FORMAT) as tar:
            for name,payload in [('manifest.json',meta),('packs/candidate.pack.gz',blob)]:
                entry=tarfile.TarInfo(name)
                entry.size=len(payload);entry.mtime=0;entry.uid=0;entry.gid=0
                entry.uname='';entry.gname='';entry.mode=0o444
                tar.addfile(entry,io.BytesIO(payload))
    return stream.getvalue(),receipt


def persist_stage(root,payload):
    root=Path(root).resolve()
    directory=root/'tools/release_publication/candidates'
    # Reject symlinked ancestors before mkdir: even a rejected candidate must
    # never create directories outside the repository through a parent link.
    for ancestor in (root/'tools', root/'tools/release_publication', directory):
        if ancestor.is_symlink():raise StageBlocked('unsafe staging directory')
    directory.mkdir(parents=True,exist_ok=True)
    if directory.resolve()!=directory.absolute():raise StageBlocked('staging escaped repository')
    final=directory/(hashlib.sha256(payload).hexdigest()+'.tar.gz')
    if final.exists() or final.is_symlink():
        if final.is_symlink() or final.read_bytes()!=payload:
            raise StageBlocked('immutable staged bytes collision')
        return final
    fd,temp=tempfile.mkstemp(dir=directory,prefix='.stage-',suffix='.tmp')
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(payload);f.flush();os.fsync(f.fileno())
        try:os.link(temp,final)
        except FileExistsError:
            if final.is_symlink() or final.read_bytes()!=payload:
                raise StageBlocked('concurrent staging collision')
        dfd=os.open(directory,os.O_RDONLY)
        try:os.fsync(dfd)
        finally:os.close(dfd)
    finally:Path(temp).unlink(missing_ok=True)
    return final


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo-root',required=True,type=Path)
    ap.add_argument('--artifact-path',required=True)
    ap.add_argument('--language',required=True)
    ap.add_argument('--sha256',required=True)
    ap.add_argument('--stage',action='store_true')
    ap.add_argument('--publish',action='store_true')
    args=ap.parse_args(argv)
    try:
        if args.publish:
            raise StageBlocked('PUBLICATION_FORBIDDEN: release is not implemented or authorized')
        payload,report=stage_bytes(args.repo_root,args.artifact_path,args.language,args.sha256)
        if args.stage:
            report['stage_path']=str(persist_stage(args.repo_root,payload))
        print(json.dumps(report,sort_keys=True))
        return 0
    except (StageBlocked,ValueError,OSError,KeyError,TypeError,ImportError) as exc:
        print(json.dumps({'status':'BLOCKED','reason':str(exc),'publication_approved':False},sort_keys=True))
        return 2

if __name__=='__main__':sys.exit(main())
