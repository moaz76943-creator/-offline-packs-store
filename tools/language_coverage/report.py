#!/usr/bin/env python3
"""Read-only sparse language coverage gap view; complements the canonical coverage_audit/check.py."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sys

LANG=re.compile(r'[a-z]{2,3}(?:-[a-z0-9]{2,8})?\Z')
SHA=re.compile(r'[a-f0-9]{64}\Z')
DIMENSIONS=('nouns','verbs','adjectives','grammar','sentences','examples','exercises','topics','pronunciation','audio','morphology','search','cefr')

def read_json(root,path):
    p=root/path
    if not p.is_file() or p.is_symlink() or p.stat().st_size>6_000_000:
        raise ValueError('missing/unsafe/oversize input '+path)
    return json.loads(p.read_text(encoding='utf-8'))

def coverage(manifest,registry,readiness,ledger,version=None,pairs=None):
    languages=manifest.get('languages'); rlangs=registry.get('languages'); states=readiness.get('states')
    if not isinstance(languages,list) or len(languages)!=100 or not isinstance(rlangs,list) or len(rlangs)!=100 or not isinstance(states,dict):
        raise ValueError('canonical 100-language sources missing')
    mids=[x.get('code') for x in languages]; rids=[x.get('id') for x in rlangs]
    if any(not isinstance(x,str) or not LANG.fullmatch(x) for x in mids) or len(set(mids))!=100 or set(mids)!=set(rids) or set(states)!=set(mids):
        raise ValueError('language identity mismatch')
    source_list=ledger.get('sources'); packs=manifest.get('packs')
    if not isinstance(source_list,list) or not isinstance(packs,list):raise ValueError('sources or packs unverified')
    admitted={x.get('source_id') for x in source_list if isinstance(x,dict) and x.get('status')=='APPROVED_FOR_REDISTRIBUTION'}
    published={x.get('id') for x in packs if isinstance(x,dict) and x.get('id') in mids}
    if len(published)!=len(packs):raise ValueError('duplicate or unregistered pack')
    if not source_list and published:raise ValueError('published pack with no approved source')
    if version is not None:
        if not isinstance(version,dict):raise ValueError('invalid version metadata')
        release=version.get('release_status')
        if not published and (version.get('packs') or release not in ('BLOCKED_DEPENDENCY',None)):
            raise ValueError('release metadata conflicts with empty published packs')
    rows=[]
    for x in sorted(languages,key=lambda y:y['code']):
        code=x['code']; released=bool(x.get('production_ready'))
        if released and (code not in published or not x.get('pack_verified') or not admitted):
            raise ValueError('unverified production readiness for '+code)
        row={'language':code,'name':x.get('name') or code,'registered':bool(x.get('registered')),
             'readiness_registry':states[code], 'production_ready':'TRUE' if released else 'FALSE',
             'canonical_pack':'DECLARED_NEEDS_BYTE_QA' if code in published else 'NOT_PUBLISHED',
             'license':'SOURCE_LANGUAGE_MAPPING_UNKNOWN' if admitted else 'NO_APPROVED_SOURCE',
             'coverage_evidence':'UNKNOWN'}
        for dim in DIMENSIONS: row[dim]='UNKNOWN'
        rows.append(row)
    sparse=[];seen=set()
    for pair in pairs or []:
        if not isinstance(pair,dict):raise ValueError('pair record not object')
        src=pair.get('source_language');target=pair.get('target_language')
        if src not in mids or target not in mids or src==target or (src,target) in seen:
            raise ValueError('unknown/duplicate directed pair')
        seen.add((src,target))
        count=pair.get('translation_count')
        valid=bool(pair.get('reviewed') is True and pair.get('license_status')=='APPROVED_FOR_REDISTRIBUTION'
                   and isinstance(pair.get('source_sha256'),str) and SHA.fullmatch(pair['source_sha256'])
                   and type(count) is int and count>=0)
        sparse.append({'source_language':src,'target_language':target,
                       'verified_count':'UNKNOWN', 'claimed_count':count if valid else 'UNKNOWN',
                       'status':'EVIDENCE_CLAIM_REQUIRES_INDEPENDENT_QA' if valid else 'UNKNOWN'})
    return {'status':'ADVISORY_ONLY','registered':100,'declared_packs':len(published),
            'approved_source_ids':len(admitted),'readiness_note':'Production identity is not proof of licensed pack bytes.',
            'language_rows':rows,'directed_pairs':sparse, 'unknown_pair_directions':'not enumerated: sparse O(N+E)',
            'canonical_release_qa':'EXTERNAL_CHECK_REQUIRED'}

def load_pairs(path):
    if path is None:return []
    if path.is_symlink() or path.stat().st_size>3_000_000:raise ValueError('unsafe pair evidence file')
    result=[]
    with path.open(encoding='utf-8') as f:
        for line in f:
            if len(line)>10000 or len(result)>=5000:raise ValueError('pair evidence bound exceeded')
            result.append(json.loads(line))
    return result

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('.'))
    p.add_argument('--pairs-jsonl',type=Path)
    p.add_argument('--output-dir',type=Path,default=Path('reports/language_coverage'))
    a=p.parse_args(argv)
    try:
        result=coverage(read_json(a.root,'manifest.json'),read_json(a.root,'catalog/language_registry.v1.json'),
                        read_json(a.root,'catalog/content_readiness.v1.json'),read_json(a.root,'legal/ledger/sources.json'),
                        read_json(a.root,'version.json'),load_pairs(a.pairs_jsonl))
        a.output_dir.mkdir(parents=True,exist_ok=True)
        (a.output_dir/'coverage.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        with (a.output_dir/'coverage.csv').open('w',encoding='utf-8',newline='') as fh:
            wr=csv.DictWriter(fh,fieldnames=list(result['language_rows'][0]));wr.writeheader();wr.writerows(result['language_rows'])
        print(json.dumps({k:v for k,v in result.items() if k not in ('language_rows','directed_pairs')},ensure_ascii=False))
        return 0
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
        print(json.dumps({'status':'UNKNOWN','reason':type(exc).__name__},ensure_ascii=False))
        return 2
if __name__=='__main__':sys.exit(main())
