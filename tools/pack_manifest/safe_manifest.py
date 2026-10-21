#!/usr/bin/env python3
"""Create immutable QA-only SQLite v2 candidate manifests; never publish packs.

Authentic corpus evidence is delegated to the canonical conformance gate.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SHA=re.compile(r'^[a-f0-9]{64}$')
LANGUAGE=re.compile(r'^[a-z]{2,3}(?:-[a-zA-Z0-9]+)*$')
MAX_ARCHIVE=40*1024*1024
MAX_SPEC=1024*1024
MAX_ENVELOPE=120*1024*1024

class ManifestBlocked(ValueError):
    pass


def strict_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_SPEC:
        raise ManifestBlocked('invalid or oversized manifest spec')
    def distinct(pairs):
        obj={}
        for k,v in pairs:
            if k in obj:raise ManifestBlocked('duplicate manifest JSON key')
            obj[k]=v
        return obj
    try:
        return json.loads(path.read_bytes().decode('utf-8'),object_pairs_hook=distinct,
                          parse_constant=lambda _: (_ for _ in ()).throw(ManifestBlocked('nonfinite JSON')))
    except (ValueError,UnicodeError,RecursionError) as exc:
        raise ManifestBlocked('malformed manifest JSON') from exc


def confined(root,rel):
    if not isinstance(rel,str) or not rel or '\\' in rel:
        raise ManifestBlocked('unsafe artifact path')
    p=Path(rel)
    if p.is_absolute() or '..' in p.parts or '.git' in p.parts:
        raise ManifestBlocked('unsafe artifact path')
    current=root
    for part in p.parts:
        current=current/part
        if current.is_symlink():raise ManifestBlocked('symlinked artifact')
    if not current.resolve().is_relative_to(root) or not current.is_file():
        raise ManifestBlocked('missing candidate archive')
    return current


def archive_bytes(path):
    """Open once, no-follow, and refuse anything larger than MAX_ARCHIVE."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as exc:
        raise ManifestBlocked('unreadable candidate archive') from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ManifestBlocked('candidate archive is not a regular file')
        if info.st_size > MAX_ARCHIVE:
            raise ManifestBlocked('candidate archive exceeds max bytes')
        chunks = []
        remaining = MAX_ARCHIVE + 1
        while remaining > 0:
            block = os.read(fd, min(1024 * 1024, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        data = b''.join(chunks)
        if len(data) > MAX_ARCHIVE:
            raise ManifestBlocked('candidate archive exceeds max bytes')
        return data
    finally:
        os.close(fd)


def inspect_gzip_bounded(blob):
    if not blob.startswith(b'\x1f\x8b'):
        raise ManifestBlocked('invalid gzip envelope')
    dec=zlib.decompressobj(16+zlib.MAX_WBITS)
    try:
        decompressed=dec.decompress(blob,MAX_ENVELOPE+1)
    except zlib.error as exc:
        raise ManifestBlocked('invalid gzip envelope') from exc
    if len(decompressed)>MAX_ENVELOPE:
        raise ManifestBlocked('gzip decompression limit exceeded')
    if not dec.eof or dec.unused_data or dec.unconsumed_tail:
        raise ManifestBlocked('invalid gzip envelope or decompression limit')
    return len(decompressed)


def manifest(root,claims):
    root=Path(root).resolve()
    if not isinstance(claims,list) or not claims:
        raise ManifestBlocked('zero candidates cannot create a release manifest')
    used_language=set()
    used_paths=set()
    packs=[]
    from tools.gha_factory.pack_conformance.check import inspect
    for claim in claims:
        if not isinstance(claim,dict) or set(claim)!={'language','artifact_path','archive_sha256'}:
            raise ManifestBlocked('incomplete candidate identity')
        lang,relative,sha=claim['language'],claim['artifact_path'],claim['archive_sha256']
        if (not isinstance(lang,str) or not LANGUAGE.fullmatch(lang)
                or lang in used_language or relative in used_paths
                or not isinstance(sha,str) or not SHA.fullmatch(sha)):
            raise ManifestBlocked('duplicate or invalid candidate identity')
        used_language.add(lang);used_paths.add(relative)
        archive=archive_bytes(confined(root,relative))
        if hashlib.sha256(archive).hexdigest()!=sha:
            raise ManifestBlocked('independent candidate archive hash mismatch')
        inspect_gzip_bounded(archive)
        report=inspect(archive,lang,root=root,allow_fixture=False,expected_sha256=sha)
        if report.get('fixture_only') or report.get('publication_approved') is True:
            raise ManifestBlocked('fixture or self-authorizing conformance report')
        if not isinstance(report.get('sqlite_sha256'),str) or not SHA.fullmatch(report['sqlite_sha256']):
            raise ManifestBlocked('missing verified independent SQLite content hash')
        packs.append({'language':lang,'artifact_path':relative,'archive_sha256':sha,
                      'sqlite_sha256':report['sqlite_sha256'],
                      'lexical_count':report['actual_lexical_count'],
                      'source_ids':sorted(report['source_ids']),
                      'schema_version':report['schema_version'],
                      'stable_ids_status':'NOT_PROVEN',
                      'rights_publication_approved':False})
    return {'manifest_version':'1.0.0','status':'QUARANTINED_CANDIDATES_ONLY',
            'packs':sorted(packs,key=lambda x:x['language']),
            'signature_verified':False,'stable_id_migration_verified':False,
            'publication_approved':False}


def diff(old,new):
    if (not isinstance(old,dict) or not isinstance(new,dict)
            or old.get('publication_approved') is not False
            or new.get('publication_approved') is not False):
        raise ManifestBlocked('only QA-only manifests may be compared')
    def keyed(doc):
        items=doc.get('packs',[])
        if not isinstance(items,list) or any(not isinstance(x,dict) or 'language' not in x for x in items):
            raise ManifestBlocked('invalid pack list')
        result={x['language']:x for x in items}
        if len(result)!=len(items):raise ManifestBlocked('duplicated language')
        return result
    before,after=keyed(old),keyed(new)
    unchanged=[];changed=[]
    for lang in sorted(set(before)&set(after)):
        if before[lang].get("sqlite_sha256")==after[lang].get("sqlite_sha256"):unchanged.append(lang)
        else:changed.append(lang)
    return {'unchanged':unchanged,'added_pending_review':sorted(set(after)-set(before)),
            'removed_pending_review':sorted(set(before)-set(after)),
            'changed_pending_stable_id_review':changed,
            'safe_to_apply':False,'publication_approved':False}


def persist(root,value):
    root=Path(root).resolve()
    if value.get('publication_approved') is not False or not value.get('packs'):
        raise ManifestBlocked('empty or publishing manifest not permitted')
    directory=root/'tools/pack_manifest/handoffs'
    if directory.is_symlink():raise ManifestBlocked('symlinked handoff directory')
    directory.mkdir(parents=True,exist_ok=True)
    if directory.resolve()!=directory.absolute():raise ManifestBlocked('unsafe output path')
    raw=(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode()
    output=directory/(hashlib.sha256(raw).hexdigest()+'.json')
    if output.is_symlink() or output.exists():
        if output.is_symlink() or output.read_bytes()!=raw:
            raise ManifestBlocked('immutable manifest collision')
        return output
    fd,temp=tempfile.mkstemp(dir=directory,prefix='.manifest-',suffix='.tmp')
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(raw);f.flush();os.fsync(f.fileno())
        try:os.link(temp,output)
        except FileExistsError:
            if output.is_symlink() or output.read_bytes()!=raw:
                raise ManifestBlocked('concurrent manifest collision')
        dfd=os.open(directory,os.O_RDONLY)
        try:os.fsync(dfd)
        finally:os.close(dfd)
    finally:Path(temp).unlink(missing_ok=True)
    return output


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo-root',type=Path,required=True)
    p.add_argument('--candidate-spec',type=Path,required=True)
    args=p.parse_args(argv)
    try:
        claims=strict_json(args.candidate_spec)
        proof=manifest(args.repo_root,claims)
        output=persist(args.repo_root,proof)
        print(json.dumps({'status':proof['status'],'handoff':str(output), 'publication_approved':False}))
        return 0
    except (ManifestBlocked,ValueError,KeyError,TypeError,ImportError,OSError) as exc:
        print(json.dumps({'status':'BLOCKED','reason':str(exc),'publication_approved':False}))
        return 2

if __name__=='__main__':sys.exit(main())
