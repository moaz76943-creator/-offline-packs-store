#!/usr/bin/env python3
"""Immutable, nonpublishing per-source provenance evidence for SQLite v2.

Never emits a completed release when no real admitted candidates exist.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

SHA=re.compile(r'^[a-f0-9]{64}$')
MAX_JSON=2*1024*1024
MAX_ARCHIVE=40*1024*1024

class ProvenanceBlocked(ValueError):
    pass


def read_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_JSON:
        raise ProvenanceBlocked('missing, symlinked or oversized JSON evidence')
    def unique(pairs):
        obj={}
        for k,v in pairs:
            if k in obj: raise ProvenanceBlocked('duplicate evidence key')
            obj[k]=v
        return obj
    try:
        return json.loads(path.read_bytes().decode('utf-8'),object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ProvenanceBlocked('nonfinite JSON')))
    except (UnicodeError,ValueError,RecursionError) as exc:
        raise ProvenanceBlocked('invalid admission JSON') from exc


def confined(root,relative):
    if not isinstance(relative,str) or not relative or '\\' in relative:
        raise ProvenanceBlocked('unsafe artifact path')
    p=Path(relative)
    if p.is_absolute() or '..' in p.parts or '.git' in p.parts:
        raise ProvenanceBlocked('unsafe artifact path')
    cur=root
    for part in p.parts:
        cur=cur/part
        if cur.is_symlink(): raise ProvenanceBlocked('symlinked artifact')
    if not cur.resolve().is_relative_to(root) or not cur.is_file():
        raise ProvenanceBlocked('missing artifact')
    return cur


def digest(path,max_size):
    if path.stat().st_size>max_size:
        raise ProvenanceBlocked('artifact too large')
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(65536),b''):
            h.update(chunk)
    return h.hexdigest()


def compile_provenance(root):
    root=Path(root).resolve()
    ledger=read_json(root/'legal/ledger/sources.json')
    manifest=read_json(root/'manifest.json')
    dailydir=root/'legal/ledger/daily'
    if dailydir.is_symlink() or not dailydir.is_dir():
        raise ProvenanceBlocked('missing daily evidence directory')
    dailies=[read_json(p) for p in sorted(dailydir.glob('*.json'))]
    if (not isinstance(ledger,dict) or not isinstance(ledger.get('sources'),list)
            or not isinstance(manifest,dict)):
        raise ProvenanceBlocked('invalid canonical manifest/ledger')
    from legal.ledger.admission import evaluate
    failures=evaluate(ledger,manifest,dailies,root)
    if failures:
        raise ProvenanceBlocked('canonical rights admission blocked: '+'; '.join(failures[:3]))
    candidates=[item for daily in dailies if isinstance(daily,dict)
                for item in daily.get('release_candidates',[]) if isinstance(item,dict)]
    if not candidates:
        raise ProvenanceBlocked('zero admitted release candidates; no processed corpus')
    sources={s['source_id']:s for s in ledger['sources'] if isinstance(s,dict) and isinstance(s.get('source_id'),str)}
    if len(sources)!=len(ledger['sources']) or not sources:
        raise ProvenanceBlocked('duplicate/empty source identities')
    outputs=[]
    seen=set()
    for candidate in sorted(candidates,key=lambda x:str(x.get('asset_id'))):
        path,sha,asset_id=candidate.get('artifact_path'),candidate.get('sha256'),candidate.get('asset_id')
        if not isinstance(asset_id,str) or not asset_id or asset_id in seen:
            raise ProvenanceBlocked('duplicate/missing asset ID')
        seen.add(asset_id)
        if not isinstance(sha,str) or not SHA.fullmatch(sha):
            raise ProvenanceBlocked('missing candidate SHA-256')
        asset=confined(root,path)
        if digest(asset,MAX_ARCHIVE)!=sha:
            raise ProvenanceBlocked('candidate hash mismatch')
        refs=candidate.get('source_refs')
        if not isinstance(refs,list) or not refs:
            raise ProvenanceBlocked('missing candidate source evidence')
        resolved=[]
        ids=set()
        for ref in refs:
            sid=ref.get('source_id') if isinstance(ref,dict) else None
            source=sources.get(sid)
            if (source is None or sid in ids or source.get('status')!='APPROVED_FOR_REDISTRIBUTION'
                    or ref.get('dataset_version')!=source.get('dataset_version')
                    or ref.get('artifact_sha256')!=source.get('retrieval',{}).get('sha256')):
                raise ProvenanceBlocked('unverified or changed source mapping')
            ids.add(sid)
            resolved.append({'source_id':sid,'dataset_version':source['dataset_version'],
                             'snapshot_sha256':source['retrieval']['sha256'],
                             'license_id':source['license']['id'],
                             'author':source.get('author'),
                             'publisher':source['publisher'], 'origin_url':source['origin_url']})
        # This compiler does not certify SQLite conformance/signature; later gates own it.
        outputs.append({'asset_id':asset_id,'artifact_path':path,'archive_sha256':sha,
                        'output_license_id':candidate.get('output_license_id'),
                        'sources':sorted(resolved,key=lambda x:x['source_id'])})
    return {'schema_version':'1.0.0','status':'QUARANTINED_PENDING_PACK_AND_SIGNATURE_QA',
            'assets':outputs,'asset_count':len(outputs),
            'sqlite_v2_verified':False,'signature_verified':False,
            'corpus_processing_succeeded':False,'publication_approved':False}


def persist(root,report):
    root=Path(root).resolve()
    if report.get('publication_approved') is not False or not report.get('assets'):
        raise ProvenanceBlocked('not eligible for nonpublishing handoff')
    destdir=root/'tools/provenance_release/handoffs'
    if destdir.is_symlink(): raise ProvenanceBlocked('symlinked handoff directory')
    destdir.mkdir(parents=True,exist_ok=True)
    if destdir.resolve()!=destdir.absolute():
        raise ProvenanceBlocked('handoff escape')
    body=(json.dumps(report,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
    filename=hashlib.sha256(body).hexdigest()+'.json'
    output=destdir/filename
    if output.exists() or output.is_symlink():
        if output.is_symlink() or output.read_bytes()!=body:
            raise ProvenanceBlocked('immutable handoff collision')
        return output
    fd,stage=tempfile.mkstemp(dir=destdir,prefix='.stage-',suffix='.tmp')
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(body);f.flush();os.fsync(f.fileno())
        try: os.link(stage,output)
        except FileExistsError:
            if output.is_symlink() or output.read_bytes()!=body:
                raise ProvenanceBlocked('concurrent handoff collision')
        directory_fd=os.open(destdir,os.O_RDONLY)
        try: os.fsync(directory_fd)
        finally: os.close(directory_fd)
    finally:
        Path(stage).unlink(missing_ok=True)
    return output


def install_repo_import_path(root):
    """Put the checkout on sys.path so a direct script run can import legal.*.

    `python tools/provenance_release/evidence.py` sets sys.path[0] to
    tools/provenance_release, which cannot see legal.ledger.admission.
    """
    resolved=str(Path(root).resolve())
    if resolved in sys.path:
        sys.path.remove(resolved)
    sys.path.insert(0, resolved)


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo-root',required=True,type=Path)
    args=ap.parse_args(argv)
    install_repo_import_path(args.repo_root)
    try:
        report=compile_provenance(args.repo_root)
        path=persist(args.repo_root,report)
        print(json.dumps({'status':report['status'],'handoff':str(path),'publication_approved':False}))
        return 0
    except (ProvenanceBlocked,OSError,ImportError,KeyError,TypeError) as exc:
        print(json.dumps({'status':'BLOCKED','reason':str(exc),'publication_approved':False}))
        return 2

if __name__=='__main__':
    sys.exit(main())
