#!/usr/bin/env python3
"""Read-only acceptance adapter: the canonical public manifest remains authoritative."""
import argparse
import base64
import binascii
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HASH = re.compile(r'^[a-f0-9]{64}$')
VERSION = re.compile(r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$')
DOMAIN = b'DEUTSCH-PUBLIC-ACCEPTANCE-v1\x00'
STAGES = ('REGISTERED','SOURCE_APPROVED','LEXICAL_VERIFIED',
          'LINGUISTIC_VERIFIED','PACK_VERIFIED','PUBLISHED',
          'APP_INSTALLATION_VERIFIED')
METRICS = ('lexemes','senses','attested_verbs','attested_forms',
           'grammar_rules','examples','audio','translations','exercises')
PROOFS = ('lexical','morphology','sentences','translations','grammar',
          'license','attribution','candidate_qa')

class AcceptanceError(ValueError):
    pass

def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AcceptanceError('duplicate JSON keys')
        result[key] = value
    return result

def read_json(path):
    p = Path(path)
    if not p.is_file() or p.is_symlink() or p.stat().st_size > 4*1024*1024:
        raise AcceptanceError('missing, unsafe or oversized JSON')
    try:
        return json.loads(p.read_text(encoding='utf-8'), object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(AcceptanceError('nonfinite JSON')))
    except (ValueError, UnicodeError) as error:
        raise AcceptanceError('invalid strict JSON') from error

def sha_file(path, limit=40*1024*1024):
    digest = hashlib.sha256()
    total = 0
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            total += len(chunk)
            if total > limit:
                raise AcceptanceError('artifact too large')
            digest.update(chunk)
    return digest.hexdigest()

def safe_file(root, relative):
    if not isinstance(relative,str) or not relative or '\\' in relative:
        raise AcceptanceError('unsafe path')
    p = Path(relative)
    if p.is_absolute() or any(part in ('.','..','.git') for part in p.parts):
        raise AcceptanceError('unsafe path')
    full = (root/p).resolve()
    if not full.is_relative_to(root.resolve()) or not full.is_file() or (root/p).is_symlink():
        raise AcceptanceError('missing or escaping artifact')
    return full

def canonical(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',',':'),
                      allow_nan=False).encode('utf-8')

def verify_signed(receipt, public_key, pinned_key_sha256, kind):
    """Domain-separated Ed25519. Trust pin is caller-owned, not receipt-provided."""
    if not isinstance(receipt,dict) or set(receipt) != {'payload','signature'}:
        raise AcceptanceError('invalid signed receipt')
    payload = receipt['payload']
    if not isinstance(payload,dict) or payload.get('kind') != kind:
        raise AcceptanceError('signed receipt identity mismatch')
    if not HASH.fullmatch(str(pinned_key_sha256)) or sha_file(public_key, 10000) != pinned_key_sha256:
        raise AcceptanceError('trusted key pin mismatch')
    if b'PRIVATE KEY' in Path(public_key).read_bytes():
        raise AcceptanceError('private signing keys forbidden')
    try:
        signature = base64.b64decode(receipt['signature'], validate=True)
    except (TypeError, ValueError, binascii.Error) as error:
        raise AcceptanceError('malformed signature') from error
    if len(signature) != 64:
        raise AcceptanceError('invalid Ed25519 signature length')
    try:
        key = subprocess.run(['openssl','pkey','-pubin','-in',str(public_key),
                              '-text','-noout'],capture_output=True,timeout=8,check=True)
        if b'ED25519 Public-Key' not in key.stdout:
            raise AcceptanceError('Ed25519 public key required')
        with tempfile.TemporaryDirectory(prefix='release-verify-') as d:
            msg = Path(d)/'msg'; sig = Path(d)/'sig'
            msg.write_bytes(DOM + canonical(payload)); sig.write_bytes(signature)
            subprocess.run(['openssl','pkeyutl','-verify','-pubin','-inkey',
                            str(public_key),'-rawin','-in',str(msg),'-sigfile',str(sig)],
                           capture_output=True,timeout=8,check=True)
    except (OSError, subprocess.SubprocessError) as error:
        raise AcceptanceError('cryptographic signature invalid') from error
    return payload

def canonical_registry(root):
    registry = read_json(root/'catalog/language_registry.v1.json')
    manifest = read_json(root/'manifest.json')
    readiness = read_json(root/'catalog/content_readiness.v1.json')
    ids = [item.get('id') for item in registry.get('languages',[])]
    published_ids = [item.get('code') for item in manifest.get('languages',[])]
    if (len(ids)!=100 or len(set(ids))!=100 or len(published_ids)!=100 or
            len(set(published_ids))!=100 or set(ids)!=set(published_ids) or
            set(readiness.get('states',{}))!=set(ids) or manifest.get('total_languages')!=100 or
            not all(isinstance(v,str) and v for v in ids) or
            not all(item.get('registered') is True for item in manifest['languages'])):
        raise AcceptanceError('100-language canonical identity mismatch')
    return ids, manifest, readiness

def snapshot(root):
    """Coverage receipt distinguishes absence from failure and N/A; never invents content."""
    root = Path(root).resolve()
    ids, manifest, readiness = canonical_registry(root)
    ledger = read_json(root/'legal/ledger/sources.json')
    version = read_json(root/'version.json')
    sources, packs = ledger.get('sources'), manifest.get('packs')
    if not isinstance(sources,list) or not isinstance(packs,list):
        raise AcceptanceError('invalid canonical inventory')
    if not sources and (packs or version.get('packs') or version.get('release_status')!='BLOCKED_DEPENDENCY'):
        raise AcceptanceError('published packs without approved source ledger')
    results = []
    for code in ids:
        status = {stage:'NOT_EVIDENCED' for stage in STAGES}
        status['REGISTERED'] = 'PASS'
        results.append({'language':code,'stages':status,'highest_verified_stage':'REGISTERED',
                        'metrics':{name:None for name in METRICS},
                        'readiness_metadata':readiness['states'][code],
                        'release_status':'NOT_EVIDENCED'})
    return {'schema_version':'production-acceptance.v1',
            'canonical_manifest_authority':'manifest.json',
            'registered':100,'source_approved_verified':0,'published_verified':0,
            'app_installation_verified':0,'languages':results,
            'production_complete_100_languages':False,'publication_approved':False,
            'status':'BLOCKED_SOURCE' if not sources else 'BLOCKED_EVIDENCE',
            'blockers':['NO_APPROVED_SOURCE_EVIDENCE'] if not sources else
                       ['INDEPENDENT_EVIDENCE_REQUIRED']}

def evaluate_candidate(root,bundle,archive,*,qa_key,qa_pin,publisher_key,publisher_pin,
                       previous_version=None):
    """Exact archive + immutable source + independent signed proofs, no publication."""
    root=Path(root).resolve()
    ids,manifest,_ = canonical_registry(root)
    b = read_json(bundle)
    item=b.get('candidate')
    if not isinstance(item,dict):
        raise AcceptanceError('candidate identity absent')
    code,version,expected=(item.get(k) for k in ('language','version','sha256'))
    if code not in ids or not isinstance(version,str) or not VERSION.fullmatch(version) or not HASH.fullmatch(str(expected)):
        raise AcceptanceError('invalid language/version/hash')
    if previous_version is not None and (not VERSION.fullmatch(previous_version) or
       tuple(map(int,version.split('.'))) <= tuple(map(int,previous_version.split('.')))):
        raise AcceptanceError('version downgrade/replay rejected')
    path=safe_file(root,archive)
    if sha_file(path)!=expected:
        raise AcceptanceError('candidate bytes hash mismatch')
    if item.get('fixture_only') is not False:
        raise AcceptanceError('synthetic fixture cannot publish')
    source=item.get('source')
    if not isinstance(source,dict) or set(source)!={'source_id','dataset_version','sha256'} or not HASH.fullmatch(str(source['sha256'])):
        raise AcceptanceError('immutable source identity absent')
    ledger=read_json(root/'legal/ledger/sources.json')
    matches=[s for s in ledger.get('sources',[]) if s.get('source_id')==source['source_id']]
    if len(matches)!=1 or matches[0].get('status')!='APPROVED_FOR_REDISTRIBUTION':
        raise AcceptanceError('source admission absent')
    actual=matches[0]
    if actual.get('dataset_version')!=source['dataset_version'] or actual.get('retrieval',{}).get('sha256')!=source['sha256']:
        raise AcceptanceError('source SHA/version changed')
    from legal.ledger.admission import evaluate
    dailies=[read_json(p) for p in sorted((root/'legal/ledger/daily').glob('*.json'))]
    if evaluate(ledger,manifest,dailies,root):
        raise AcceptanceError('Route05 license/attribution/source verification blocked')
    # A matching daily candidate record is necessary; a source-level license
    # record alone does not legally clear the bytes of a new derivative pack.
    matching=[]
    for day in dailies:
        for entry in day.get('release_candidates',[]):
            refs=entry.get('source_refs',[]) if isinstance(entry,dict) else []
            if (isinstance(entry,dict) and entry.get('sha256')==expected and
                entry.get('artifact_path')==archive and
                any(isinstance(ref,dict) and ref.get('source_id')==source['source_id']
                    and ref.get('dataset_version')==source['dataset_version']
                    and ref.get('artifact_sha256')==source['sha256'] for ref in refs)):
                matching.append(entry)
    if len(matching)!=1:
        raise AcceptanceError('exact Route05 daily candidate and source proof absent')
    from tools.gha_factory.pack_conformance.check import inspect
    result=inspect(path.read_bytes(),code,root=root,allow_fixture=False,expected_sha256=expected)
    if result.get('fixture_only') is not False or result.get('archive_sha256')!=expected:
        raise AcceptanceError('strict SQLite v2 exact candidate failed')
    proofs=b.get('proofs')
    if not isinstance(proofs,dict) or set(proofs)!=set(PROOFS):
        raise AcceptanceError('independent signed proof set absent')
    for kind in PROOFS:
        proof=verify_signed(proofs[kind],qa_key,qa_pin,kind)
        for field,value in (('language',code),('version',version),('pack_sha256',expected),
                            ('source_id',source['source_id']),('dataset_version',source['dataset_version']),
                            ('source_sha256',source['sha256'])):
            if proof.get(field)!=value:
                raise AcceptanceError('proof cross-pack/source substitution')
        if proof.get('result')!='PASS' or type(proof.get('run_id')) is not int or proof['run_id']<1:
            raise AcceptanceError('independent QA proof absent or failed')
    # A publisher-signed installation floor binds the previous canonical release.
    # Client-supplied version strings alone never establish an anti-rollback floor.
    state=verify_signed(b.get('release_state'),publisher_key,publisher_pin,'release_state')
    if state.get('language')!=code:
        raise AcceptanceError('cross-language signed release state')
    present=[p for p in manifest.get('packs',[]) if isinstance(p,dict) and
             (p.get('id')==code or p.get('languageCode')==code)]
    if state.get('mode')=='GENESIS':
        if present:
            raise AcceptanceError('cannot declare genesis over published pack')
        floor='0.0.0'
        lkg_sha=None
    elif state.get('mode')=='LAST_KNOWN_GOOD':
        if len(present)!=1:
            raise AcceptanceError('canonical Last-Known-Good manifest entry absent')
        old=present[0]
        floor=state.get('version')
        lkg_sha=state.get('sha256')
        if (not isinstance(floor,str) or not VERSION.fullmatch(floor) or
                not HASH.fullmatch(str(lkg_sha)) or
                old.get('version')!=floor or old.get('sha256')!=lkg_sha):
            raise AcceptanceError('Last-Known-Good version/hash not pinned to canonical manifest')
        lkg=safe_file(root,'packs/'+code+'-'+floor+'.pack.gz')
        if sha_file(lkg)!=lkg_sha:
            raise AcceptanceError('Last-Known-Good bytes missing or altered')
    else:
        raise AcceptanceError('signed release floor is missing')
    if tuple(map(int,version.split('.'))) <= tuple(map(int,floor.split('.'))):
        raise AcceptanceError('release replay/downgrade below signed floor')
    auth=verify_signed(b.get('authorization'),publisher_key,publisher_pin,'publication_authorization')
    for field,value in (('language',code),('version',version),('pack_sha256',expected),
                        ('source_sha256',source['sha256'])):
        if auth.get(field)!=value:
            raise AcceptanceError('release authorization identity mismatch')
    if auth.get('decision')!='APPROVE' or type(auth.get('run_id')) is not int or auth['run_id']<1:
        raise AcceptanceError('publisher authorization absent')
    return {'schema_version':'production-acceptance.v1','language':code,'version':version,
            'pack_sha256':expected,'source':source,'sqlite_v2':'PASS',
            'independent_receipts':sorted(PROOFS),'last_known_good_sha256':lkg_sha,
            'publication_handoff_eligible':True,
            'published':False,'app_installation_verified':False,'publication_approved':False,
            'status':'VERIFIED_FOR_AUTHORIZED_HANDOFF'}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('.'))
    p.add_argument('--output',type=Path)
    p.add_argument('--bundle',type=Path)
    p.add_argument('--archive')
    p.add_argument('--qa-public-key',type=Path)
    p.add_argument('--qa-key-sha256')
    p.add_argument('--publisher-public-key',type=Path)
    p.add_argument('--publisher-key-sha256')
    p.add_argument('--previous-version')
    a=p.parse_args(argv)
    try:
        if a.bundle:
            if not all((a.archive,a.qa_public_key,a.qa_key_sha256,
                        a.publisher_public_key,a.publisher_key_sha256)):
                raise AcceptanceError('required trust root or candidate absent')
            result=evaluate_candidate(a.root,a.bundle,a.archive,qa_key=a.qa_public_key,
                 qa_pin=a.qa_key_sha256,publisher_key=a.publisher_public_key,
                 publisher_pin=a.publisher_key_sha256,previous_version=a.previous_version)
        else:
            result=snapshot(a.root)
        data=json.dumps(result,sort_keys=True,ensure_ascii=False,allow_nan=False,indent=2)+'\n'
        if a.output:
            a.output.parent.mkdir(parents=True,exist_ok=True)
            a.output.write_text(data,encoding='utf-8')
        print(data,end='')
        return 0
    except (AcceptanceError,OSError,ImportError,ValueError) as error:
        print(json.dumps({'status':'BLOCKED','publication_approved':False,'reason':str(error)}))
        return 2

if __name__=='__main__':
    sys.exit(main())
