#!/usr/bin/env python3
"""Route 05-owned, fail-closed, offline source-admission staging for a future GHA queue.

This module NEVER approves a source: Route 05 reviewers own legal/ledger/sources.json.
It does not fetch data or license terms, synthesize lexemes, or infer CEFR grades.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from legal.ledger.license_notice import MAX_LICENSE_NOTICE_BYTES, license_notice_conflicts

SOURCE_SCHEMA = '1.0.0'
ROUTE05_LICENSES = frozenset({'CC0-1.0','CC-BY-SA-4.0','GFDL-1.3-only','PUBLIC-DOMAIN'})
SHA = re.compile(r'^[0-9a-f]{64}$')
ID = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$')
MAX_LINE = 1024 * 1024


class AdmissionError(ValueError):
    """Explicit denial; caller must not enqueue incomplete data."""


def digest_file(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def canon(value):
    return (json.dumps(value,sort_keys=True,ensure_ascii=False,
                       separators=(',',':'),allow_nan=False)+'\n').encode('utf-8')


def checked_file(root, relative, expected, label):
    if not isinstance(relative,str) or not relative or not isinstance(expected,str) or not SHA.fullmatch(expected):
        raise AdmissionError(f'BLOCKED_SOURCE: {label} missing path/SHA-256')
    p=Path(relative)
    if p.is_absolute() or '..' in p.parts or '.git' in p.parts:
        raise AdmissionError(f'BLOCKED_SOURCE: {label} unsafe path')
    root = root.resolve()
    candidate = root
    for part in p.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise AdmissionError(f'BLOCKED_SOURCE: {label} symlink evidence path is forbidden')
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError) as exc:
        raise AdmissionError(f'BLOCKED_SOURCE: {label} unresolvable evidence path') from exc
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise AdmissionError(f'BLOCKED_SOURCE: {label} missing/escaping evidence file')
    if digest_file(resolved)!=expected:
        raise AdmissionError(f'BLOCKED_SOURCE: {label} hash mismatch')
    return resolved


def https_url(url):
    if not isinstance(url,str):return False
    try:
        u=urlsplit(url)
        return u.scheme=='https' and bool(u.hostname) and not (u.username or u.password)
    except ValueError:return False


def registry_metadata(repo_root):
    path=repo_root/'catalog/language_registry.v1.json'
    try:
        root=json.loads(path.read_text(encoding='utf-8'))
        if root.get('schema_version')!='1.0.0' or not isinstance(root['languages'],list):
            raise ValueError('incorrect registry')
        ids=[r['id'] for r in root['languages']]
        if len(ids)!=len(set(ids)) or not all(isinstance(i,str) and i for i in ids):
            raise ValueError('invalid identities')
        if not all(isinstance(r.get('default_script'),str) and r['default_script'] for r in root['languages']):
            raise ValueError('missing script identity')
        return {r['id']:r['default_script'] for r in root['languages']}
    except (OSError,ValueError,KeyError,TypeError) as e:
        raise AdmissionError('BLOCKED_SOURCE: missing/invalid Route 03 language registry') from e


def registered_languages(repo_root):
    return frozenset(registry_metadata(repo_root))


def route05_source(repo_root, source_id, dataset_version, input_path, fmt):
    """Consume only current Route 05 owner-approved evidence (never write its ledger)."""
    ledger_path=repo_root/'legal/ledger/sources.json'
    try:
        root=json.loads(ledger_path.read_text(encoding='utf-8'))
        if root.get('schema_version')!='1.0.0' or not isinstance(root.get('sources'),list):
            raise ValueError('ledger version')
    except (OSError, ValueError, TypeError) as e:
        raise AdmissionError('BLOCKED_SOURCE: Route 05 ledger unavailable/invalid') from e
    sources=[s for s in root['sources'] if isinstance(s,dict) and s.get('source_id')==source_id]
    if len(sources)!=1:
        raise AdmissionError('BLOCKED_SOURCE: source missing/duplicate in Route 05 ledger')
    s=sources[0]
    if s.get('status')!='APPROVED_FOR_REDISTRIBUTION':
        raise AdmissionError('BLOCKED_SOURCE: Route 05 reviewer approval absent')
    from legal.ledger.admission import metadata_only_source_artifact
    if metadata_only_source_artifact(s):
        raise AdmissionError('BLOCKED_SOURCE: index/statistics bytes are not the corpus')
    if s.get('kind')!='dictionary' or fmt not in ('wiktextract-jsonl', 'wikidata-lexeme-json'):
        raise AdmissionError('BLOCKED_SOURCE: unsupported kind/format; sentences and human audio require separate adapters and rights')
    if fmt == 'wikidata-lexeme-json':
        retrieval = s.get('retrieval') or {}
        url = retrieval.get('url', '')
        match = re.fullmatch(r'https://www[.]wikidata[.]org/wiki/Special:EntityData/(L[1-9][0-9]*)[.]json[?]revision=([1-9][0-9]*)', url) if isinstance(url, str) else None
        if (s.get('license', {}).get('id') != 'CC0-1.0' or not match
                or s.get('origin_url') != url
                or retrieval.get('identity') != 'wikidata:Lexeme:%s:revision:%s' % match.groups()):
            raise AdmissionError('BLOCKED_SOURCE: Wikidata original revision/CC0 provenance required')
    if s.get('dataset_version')!=dataset_version:
        raise AdmissionError('BLOCKED_SOURCE: unapproved source version')
    license_info=s.get('license') or {}
    lid=license_info.get('id')
    if lid not in ROUTE05_LICENSES:
        raise AdmissionError('BLOCKED_SOURCE: license family unsupported by Route 05; owner review required')
    if lid=='GFDL-1.3-only':
        raise AdmissionError('BLOCKED_SOURCE: GFDL needs Route 05 documented obligation review and compatible release adapter')
    if lid=='PUBLIC-DOMAIN':
        p=license_info.get('public_domain_proof') or {}
        if not all(isinstance(p.get(k),str) and p[k].strip() for k in ('jurisdiction','legal_basis','work_date')):
            raise AdmissionError('BLOCKED_SOURCE: public-domain jurisdiction proof absent')
    if not all(isinstance(s.get(k),str) and s[k].strip() for k in ('origin_url','publisher')):
        raise AdmissionError('BLOCKED_SOURCE: incomplete publisher/provenance')
    retrieval=s.get('retrieval') or {}
    reviewer=s.get('review') or {}
    for u in (s.get('origin_url'),retrieval.get('url'),license_info.get('evidence_url'),reviewer.get('decision_url')):
        if not https_url(u):
            raise AdmissionError('BLOCKED_SOURCE: origin/license/reviewer URL must be HTTPS')
    evidence_url=license_info['evidence_url']
    if any(d in urlsplit(evidence_url).hostname.lower() for d in ('creativecommons.org','gnu.org')):
        raise AdmissionError('BLOCKED_SOURCE: generic license text is not source-specific evidence')
    if not reviewer.get('reviewer') or not isinstance(s.get('alterations'),list) or not s['alterations']:
        raise AdmissionError('BLOCKED_SOURCE: Route 05 reviewer or alteration history missing')
    try:
        date.fromisoformat(retrieval['date'])
    except (ValueError,KeyError,TypeError) as e:
        raise AdmissionError('BLOCKED_SOURCE: source snapshot date missing') from e
    if not retrieval.get('identity'):
        raise AdmissionError('BLOCKED_SOURCE: source immutable snapshot identity missing')
    source=checked_file(repo_root,retrieval.get('artifact_path'),retrieval.get('sha256'),'source')
    if source!=input_path.resolve():
        raise AdmissionError('BLOCKED_SOURCE: source path differs from reviewed Route 05 artifact')
    license_proof = checked_file(
        repo_root, license_info.get('evidence_path'),
        license_info.get('evidence_sha256'), 'license evidence')
    if license_notice_conflicts(
            license_proof, lid, license_info.get('co_offered_licenses', ())):
        raise AdmissionError('BLOCKED_SOURCE: license notice conflicts with metadata or cannot be safely checked')
    return s


SCRIPT_NAMES={'Latn':('LATIN',),'Arab':('ARABIC',),'Cyrl':('CYRILLIC',),
              'Hans':('CJK',),'Hant':('CJK',),'Jpan':('CJK','HIRAGANA','KATAKANA'),
              'Kore':('HANGUL','CJK'),'Hebr':('HEBREW',),'Grek':('GREEK',),
              'Deva':('DEVANAGARI',),'Beng':('BENGALI',),'Thai':('THAI',),
              'Ethi':('ETHIOPIC',),'Geor':('GEORGIAN',),'Armn':('ARMENIAN',),
              'Taml':('TAMIL',),'Telu':('TELUGU',),'Knda':('KANNADA',),
              'Mlym':('MALAYALAM',),'Gujr':('GUJARATI',),'Guru':('GURMUKHI',),
              'Sinh':('SINHALA',),'Khmr':('KHMER',),'Laoo':('LAO',),
              'Mymr':('MYANMAR',),'Tibt':('TIBETAN',),'Mong':('MONGOLIAN',)}


def script_valid(word, script):
    tags=SCRIPT_NAMES.get(script)
    if not tags:return False  # needs new, independently verified script gate
    letters=[unicodedata.name(c,'') for c in word if unicodedata.category(c).startswith('L')]
    return bool(letters) and sum(any(tag in name for tag in tags) for name in letters)*5 >= len(letters)*3


def extract(row, language, license_id, source_id, script, line):
    if not isinstance(row,dict):
        raise AdmissionError(f'REJECTED_RECORD: line {line}: JSONL object expected')
    if row.get('lang_code')!=language:
        raise AdmissionError(f'REJECTED_RECORD: line {line}: wrong/missing language identity')
    if 'license_id' in row and row['license_id']!=license_id:
        raise AdmissionError(f'REJECTED_RECORD: line {line}: record license differs from reviewed source')
    if 'source_id' in row and row['source_id']!=source_id:
        raise AdmissionError(f'REJECTED_RECORD: line {line}: source identity conflicts with reviewed Route 05 source')
    word,pos,senses=row.get('word'),row.get('pos'),row.get('senses')
    if not all(isinstance(v,str) and v.strip() and len(v)<=256 for v in (word,pos)) or not isinstance(senses,list):
        raise AdmissionError(f'REJECTED_RECORD: line {line}: missing lexical fields')
    if not script_valid(word,script):
        raise AdmissionError(f'REJECTED_RECORD: line {line}: wrong/unverified script for language')
    glosses=[]
    for sense in senses:
        if not isinstance(sense,dict) or not isinstance(sense.get('glosses'),list):
            raise AdmissionError(f'REJECTED_RECORD: line {line}: malformed glosses')
        for gloss in sense['glosses']:
            if not isinstance(gloss,str) or not gloss.strip() or len(gloss)>10000:
                raise AdmissionError(f'REJECTED_RECORD: line {line}: malformed definition')
            glosses.append(gloss)
    if not glosses:
        raise AdmissionError(f'REJECTED_RECORD: line {line}: no attested definitions')
    excluded=[]
    if any(isinstance(s,dict) and s.get('examples') for s in senses): excluded.append('examples')
    if row.get('sounds'):excluded.append('human_audio')
    # Do not propagate example sentences, sound recordings, CEFR guesses or unchecked
    # translations: those require their own evidence chain and adapter.
    content={'word':word,'pos':pos,'senses':glosses}
    return content,excluded


def admit(*,repo_root,source_id,input_path,out_dir,language,dataset_version,
          format_name='wiktextract-jsonl',part_size=1000):
    repo_root=Path(repo_root).resolve();input_path=Path(input_path)
    out_dir=Path(out_dir).absolute()
    if not isinstance(source_id,str) or not ID.fullmatch(source_id):
        raise AdmissionError('BLOCKED_SOURCE: invalid source ID')
    if not isinstance(part_size,int) or isinstance(part_size,bool) or not (1<=part_size<=100000):
        raise AdmissionError('BLOCKED_SOURCE: unsafe partition size')
    catalog=registry_metadata(repo_root)
    if language not in catalog:
        raise AdmissionError('BLOCKED_SOURCE: language not in verified 100-language registry')
    if format_name == 'wikidata-lexeme-json':
        from tools.gha_factory.admission.wikidata_lexeme_adapter import admit_lexeme
        return admit_lexeme(repo_root=repo_root, source_id=source_id,
                            input_path=input_path, out_dir=out_dir,
                            language=language, dataset_version=dataset_version,
                            part_size=part_size, script=catalog[language])
    source=route05_source(repo_root,source_id,dataset_version,input_path,format_name)
    if out_dir.exists() or out_dir.is_symlink():
        raise AdmissionError('BLOCKED_SOURCE: output already exists (no overwrite)')
    if not out_dir.parent.is_dir():
        raise AdmissionError('BLOCKED_SOURCE: output parent directory missing')
    lic=source['license'];retrieval=source['retrieval']
    sha_source=retrieval['sha256'];jobs=[];records=0;parts=0
    stage=Path(tempfile.mkdtemp(prefix='.admission-',dir=out_dir.parent))
    try:
        h=None;file_handle=None;part_records=0;part_file=None
        with input_path.open('rb') as stream:
            for line,raw in enumerate(iter(lambda: stream.readline(MAX_LINE + 1), b''), start=1):
                if not raw or len(raw)>MAX_LINE or not raw.endswith(b'\n') or raw.startswith(b'\xef\xbb\xbf'):
                    raise AdmissionError(f'REJECTED_RECORD: line {line}: invalid JSONL framing/encoding')
                try:
                    doc=json.loads(raw.decode('utf-8'),parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
                except (UnicodeError,ValueError) as e:
                    raise AdmissionError(f'REJECTED_RECORD: line {line}: invalid UTF-8/JSON') from e
                content,excluded=extract(doc,language,lic['id'],source_id,catalog[language],line)
                if file_handle is None:
                    part_file=f'partition-{parts:08d}.jsonl';file_handle=(stage/part_file).open('wb')
                    h=hashlib.sha256();part_records=0
                out={'source_id':source_id,'dataset_version':dataset_version,'language':language,
                     'license_id':lic['id'],'source_artifact_sha256':sha_source,
                     'license_evidence_sha256':lic['evidence_sha256'],
                     'source_line':line,'source_line_sha256':hashlib.sha256(raw).hexdigest(),
                     'excluded_categories':excluded,'content':content}
                encoded=canon(out);file_handle.write(encoded);h.update(encoded)
                part_records+=1;records+=1
                if part_records==part_size:
                    file_handle.flush();os.fsync(file_handle.fileno());file_handle.close();file_handle=None
                    job={'source_id':source_id,'dataset_version':dataset_version,'language':language,
                         'category':'dictionary','path':part_file,'sha256':h.hexdigest(),
                         'record_count':part_records,'partition_index':parts,
                         'license_id':lic['id'],'license_evidence_sha256':lic['evidence_sha256']}
                    job['resume_id']='srcadm1-'+hashlib.sha256(canon([sha_source,job])).hexdigest()[:40]
                    jobs.append(job);parts+=1
        if file_handle is not None:
            file_handle.flush();os.fsync(file_handle.fileno());file_handle.close()
            job={'source_id':source_id,'dataset_version':dataset_version,'language':language,
                 'category':'dictionary','path':part_file,'sha256':h.hexdigest(),
                 'record_count':part_records,'partition_index':parts,
                 'license_id':lic['id'],'license_evidence_sha256':lic['evidence_sha256']}
            job['resume_id']='srcadm1-'+hashlib.sha256(canon([sha_source,job])).hexdigest()[:40]
            jobs.append(job)
        if not records:
            raise AdmissionError('REJECTED_RECORD: empty source artifact')
        report={'schema_version':SOURCE_SCHEMA,'status':'ACCEPTED_FOR_QUEUE',
                'source_id':source_id,'dataset_version':dataset_version,'language':language,
                'source_artifact_sha256':sha_source,
                'license_evidence_sha256':lic['evidence_sha256'],
                'route05_reviewer_decision_url':source['review']['decision_url'],
                'actual_accepted_records':records,'jobs':jobs,
                'publication_approved':False,
                'note':'Queue-ready for separate Route 05 candidate and release gates; NOT a published pack.'}
        (stage/'queue.json').write_bytes(canon(report))
        # Exclusive rename: a concurrent run must not be overwritten.
        if out_dir.exists() or out_dir.is_symlink():
            raise AdmissionError('BLOCKED_SOURCE: output concurrently created')
        stage.rename(out_dir)
        return report
    finally:
        if stage.exists():shutil.rmtree(stage)


def load_reviews(path):
    try:
        obj=json.loads(Path(path).read_text(encoding='utf-8'))
        if obj.get('schema_version')!=SOURCE_SCHEMA or not isinstance(obj.get('sources'),list):
            raise ValueError('invalid review file')
        return obj
    except (OSError,ValueError) as e:raise AdmissionError('invalid candidate review registry') from e


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo-root',type=Path,default=Path.cwd())
    p.add_argument('--ledger-source-id',required=True)
    p.add_argument('--input',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    p.add_argument('--language',required=True)
    p.add_argument('--dataset-version',required=True)
    p.add_argument('--format',default='wiktextract-jsonl',choices=['wiktextract-jsonl', 'wikidata-lexeme-json'])
    p.add_argument('--part-size',type=int,default=1000)
    a=p.parse_args(argv)
    try:
        result=admit(repo_root=a.repo_root,source_id=a.ledger_source_id,input_path=a.input,
                     out_dir=a.out,language=a.language,dataset_version=a.dataset_version,
                     format_name=a.format,part_size=a.part_size)
    except (AdmissionError,OSError) as e:
        print(f'BLOCKED_SOURCE: {e}',file=sys.stderr)
        return 2
    print(json.dumps({k:v for k,v in result.items() if k!='jobs'},sort_keys=True))
    return 0


if __name__=='__main__':sys.exit(main())
