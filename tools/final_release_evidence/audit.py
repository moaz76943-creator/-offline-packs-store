#!/usr/bin/env python3
"""Offline truth-in-reporting guard: no receipt can fabricate corpus jobs or source rights."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

MAX_METADATA=2*1024*1024

class EvidenceBlocked(ValueError):
    pass


def strict_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_METADATA:
        raise EvidenceBlocked('missing, symlinked or oversized evidence')
    def distinct(items):
        value={}
        for k,v in items:
            if k in value:raise EvidenceBlocked('duplicate evidence JSON key')
            value[k]=v
        return value
    try:
        return json.loads(path.read_bytes().decode('utf-8'),object_pairs_hook=distinct,
                          parse_constant=lambda _: (_ for _ in ()).throw(EvidenceBlocked('invalid number')))
    except (ValueError,UnicodeError,RecursionError) as exc:
        raise EvidenceBlocked('invalid evidence JSON') from exc


def audit(root,job_receipt=None):
    root=Path(root).resolve()
    manifest=strict_json(root/'manifest.json')
    ledger=strict_json(root/'legal/ledger/sources.json')
    version=strict_json(root/'version.json')
    if not all(isinstance(value,dict) for value in (manifest,ledger,version)):
        raise EvidenceBlocked('canonical evidence JSON must be objects')
    languages=manifest.get('languages')
    if not isinstance(languages,list):
        raise EvidenceBlocked('canonical registered languages absent')
    ids=[x.get('code') for x in languages if isinstance(x,dict)]
    if len(ids)!=len(languages) or len(ids)!=100 or len(set(ids))!=100:
        raise EvidenceBlocked('100 language identities not preserved')
    if not isinstance(ledger.get('sources'),list):
        raise EvidenceBlocked('invalid source rights ledger')
    candidates=manifest.get('packs')
    if not isinstance(candidates,list):
        raise EvidenceBlocked('invalid public pack list')
    verified_sources=[s for s in ledger['sources'] if isinstance(s,dict)
                      and s.get('status')=='APPROVED_FOR_REDISTRIBUTION']
    verified_packs=0  # Offline metadata cannot prove a complete artifact/release.
    reasons=[]
    if not verified_sources:reasons.append('NO_APPROVED_SOURCE_EVIDENCE')
    if manifest.get('intellectual_property_status')=='UNVERIFIED_RIGHTS':
        reasons.append('UNVERIFIED_RIGHTS')
    if not candidates:reasons.append('NO_PRODUCTION_PACK_DESCRIPTORS')
    if version.get('release_status')!='VERIFIED_CANDIDATE':
        reasons.append('VERSION_NOT_VERIFIED')
    if version.get('latest_verified_version') is None:
        reasons.append('NO_VERIFIED_RELEASE_VERSION')
    if job_receipt is None:
        job_state='NOT_RUN'
        claimed=0
    else:
        if (not isinstance(job_receipt,dict)
                or type(job_receipt.get('claimed_jobs')) is not int
                or job_receipt['claimed_jobs']<0):
            raise EvidenceBlocked('invalid workflow job receipt')
        claimed=job_receipt['claimed_jobs']
        job_state='NOT_RUN' if claimed==0 else 'UNVERIFIED_EXTERNAL_CLAIM'
    if claimed==0:reasons.append('NO_CLAIMED_WORKFLOW_JOBS')
    else:reasons.append('WORKFLOW_JOBS_NOT_INDEPENDENTLY_VERIFIED')
    status='BLOCKED_SOURCE' if not verified_sources else 'BLOCKED_DEPENDENCY'
    return {'evidence_version':'1.0.0','status':status,'blockers':sorted(set(reasons)),
            'languages_registered':len(ids), 'approved_ledger_source_claims':len(verified_sources),
            'production_pack_descriptors':len(candidates),
            'verified_real_packs':verified_packs,
            'workflow_claimed_jobs':claimed,'workflow_validation':job_state,
            'workflow_jobs_independently_verified':False,
            'corpus_processing_succeeded':False,
            'release_ready':False,'publication_approved':False}


def persist(root,report):
    root=Path(root).resolve()
    if report.get('publication_approved') is not False or report.get('release_ready') is not False:
        raise EvidenceBlocked('cannot issue publication approval from metadata')
    directory=root/'tools/final_release_evidence/handoffs'
    if directory.is_symlink():raise EvidenceBlocked('unsafe output directory')
    directory.mkdir(parents=True,exist_ok=True)
    if directory.resolve()!=directory.absolute():raise EvidenceBlocked('escaped output directory')
    raw=(json.dumps(report,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
    output=directory/(hashlib.sha256(raw).hexdigest()+'.json')
    if output.exists() or output.is_symlink():
        if output.is_symlink() or output.read_bytes()!=raw:
            raise EvidenceBlocked('immutable evidence collision')
        return output
    fd,temp=tempfile.mkstemp(dir=directory,prefix='.evidence-',suffix='.tmp')
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(raw);f.flush();os.fsync(f.fileno())
        try:os.link(temp,output)
        except FileExistsError:
            if output.is_symlink() or output.read_bytes()!=raw:
                raise EvidenceBlocked('concurrent evidence collision')
        dfd=os.open(directory,os.O_RDONLY)
        try:os.fsync(dfd)
        finally:os.close(dfd)
    finally:Path(temp).unlink(missing_ok=True)
    return output


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo-root',type=Path,required=True)
    ap.add_argument('--workflow-receipt',type=Path)
    args=ap.parse_args(argv)
    try:
        claims=strict_json(args.workflow_receipt) if args.workflow_receipt else None
        report=audit(args.repo_root,claims)
        path=persist(args.repo_root,report)
        print(json.dumps({'status':report['status'],'handoff':str(path),'publication_approved':False}))
        return 2  # A metadata-only report is never a successful production release.
    except (EvidenceBlocked,OSError,KeyError,TypeError) as exc:
        print(json.dumps({'status':'BLOCKED','reason':str(exc),'publication_approved':False}))
        return 2

if __name__=='__main__':sys.exit(main())
