"""Gated source snapshot processing. Stdlib only; no private dependencies."""
from __future__ import annotations
import argparse
import bz2
import gzip
import hashlib
import http.client
import ipaddress
import json
import lzma
import os
import re
import shutil
import socket
import ssl
import tempfile
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
from tools.gha_factory.admission import pipeline as admission

CHUNK = 262144
MAX_LINE = 1048576
MAX_SHARDS = 100000
FORMATS = {'jsonl':open, 'jsonl.gz':gzip.open, 'jsonl.bz2':bz2.open, 'jsonl.xz':lzma.open}
SHA = re.compile(r'^[0-9a-f]{64}$')
class Blocked(ValueError):
    pass

def sha_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(CHUNK),b''):
            h.update(b)
    return h.hexdigest()

def encode(data):
    return (json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()

def atomic(path,data):
    p=Path(path)
    fd,temp=tempfile.mkstemp(dir=p.parent,prefix='.snapshot-')
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(encode(data));stream.flush();os.fsync(stream.fileno())
        os.replace(temp,p)
    finally:
        if os.path.exists(temp):os.unlink(temp)

def reviewed_url(url,host):
    try:
        u=urlsplit(url);port=u.port
        if not (u.scheme=='https' and u.hostname and host and u.hostname.lower()==host.lower()
                and port in (None,443) and not u.username and not u.password and not u.fragment
                and re.fullmatch(r'[A-Za-z0-9.-]+',u.hostname)
                and len(url)<=2048 and not any(ord(c)<32 for c in url)):
            raise ValueError('unreviewed endpoint')
        try:ipaddress.ip_address(u.hostname)
        except ValueError:pass
        else:raise ValueError('IP literal')
        if any(x.split('=')[0].lower() in {'token','key','signature','password','auth','access_token'}
               for x in u.query.split('&') if x):raise ValueError('query credential')
        return (u.path or '/')+('?' + u.query if u.query else '')
    except (ValueError,TypeError) as error:
        raise Blocked('BLOCKED_SOURCE: unsafe HTTPS URL') from error

def approved(root,sid,lang,version):
    root=Path(root).resolve()
    try:
        ids=admission.registry_metadata(root)
        ledger=json.loads((root/'legal/ledger/sources.json').read_text())
        if ledger.get('schema_version')!='1.0.0' or lang not in ids:raise ValueError('registry')
        matches=[x for x in ledger['sources'] if isinstance(x,dict) and x.get('source_id')==sid]
        if len(matches)!=1:raise ValueError('unapproved source')
        src=matches[0]
        if (src.get('status')!='APPROVED_FOR_REDISTRIBUTION' or src.get('kind')!='dictionary'
                or src.get('dataset_version')!=version):raise ValueError('review')
        r=src['retrieval'];lic=src['license'];rev=src['review']
        if (lic.get('id') not in admission.ROUTE05_LICENSES or lic['id']=='GFDL-1.3-only'
                or not rev.get('reviewer') or not r.get('identity') or not src.get('publisher')
                or not src.get('alterations') or not date.fromisoformat(r['date'])):
            raise ValueError('provenance')
        if lic['id']=='PUBLIC-DOMAIN' and not all((lic.get('public_domain_proof') or {}).get(k)
                  for k in ('jurisdiction','legal_basis','work_date')):raise ValueError('public domain')
        for url in (src['origin_url'],r['url'],lic['evidence_url'],rev['decision_url']):
            if not admission.https_url(url):raise ValueError('rights URL')
        if any(x in urlsplit(lic['evidence_url']).hostname.lower() for x in ('creativecommons.org','gnu.org')):
            raise ValueError('generic license text')
        admission.checked_file(root,lic.get('evidence_path'),lic.get('evidence_sha256'),'license')
        if not SHA.fullmatch(str(r.get('sha256',''))):raise ValueError('source hash')
        host=urlsplit(r['url']).hostname
        reviewed_url(r['url'],host)
        rel=r.get('artifact_path')
        if not isinstance(rel,str) or Path(rel).is_absolute() or '..' in Path(rel).parts:
            raise ValueError('artifact path')
        # GHA-01 currently requires the exact reviewed local artifact. No missing
        # artifact may turn a remote URL into an implicit approval.
        admission.route05_source(root,sid,version,root/rel,'wiktextract-jsonl')
        return {'source_id':sid,'language':lang,'dataset_version':version,'source_sha256':r['sha256'],
                'url':r['url'],'host':host,'identity':r['identity'],'license_id':lic['id'],
                'license_sha256':lic['evidence_sha256'],'script':ids[lang]}
    except (OSError,ValueError,TypeError,KeyError,AttributeError) as error:
        raise Blocked('BLOCKED_SOURCE: Route 05/GHA-01 review missing or invalid') from error

def verified(path,source,size):
    path=Path(path)
    if (type(size)!=int or not 0<size<=16*1024**3 or path.is_symlink()
            or not path.is_file() or path.stat().st_size!=size
            or sha_file(path)!=source['source_sha256']):
        raise Blocked('BLOCKED_SOURCE: partial/changed source bytes')
    return True

class PublicHTTPS(http.client.HTTPSConnection):
    def connect(self):
        addr=socket.getaddrinfo(self.host,443,type=socket.SOCK_STREAM)
        ips={r[4][0] for r in addr}
        if not ips or not all(ipaddress.ip_address(ip).is_global for ip in ips):
            raise Blocked('BLOCKED_SOURCE: unsafe DNS response')
        sock=None
        for ip in sorted(ips):
            try:
                sock=socket.create_connection((ip,443),timeout=self.timeout);break
            except OSError:continue
        if sock is None:raise OSError('reviewed host unavailable')
        try:self.sock=self._context.wrap_socket(sock,server_hostname=self.host)
        except BaseException:sock.close();raise

def download(source,out,size,attempts=3,delay=time.sleep):
    """Closed pending GHA-02 authenticated lease and approved source host/rate contract.

    The lower-level transport is deliberately unreachable to untrusted callers.
    GHA-02 currently cannot authenticate source_snapshot leases.
    """
    raise Blocked('BLOCKED_DEPENDENCY_GHA02: no authenticated snapshot lease/handoff')
    if type(attempts)!=int or not 1<=attempts<=3 or type(size)!=int or not 0<size<=16*1024**3:
        raise Blocked('BLOCKED_SOURCE: missing reviewed download bounds')
    target=reviewed_url(source['url'],source['host']);out=Path(out)
    if out.is_symlink() or not out.parent.is_dir():raise Blocked('BLOCKED_SOURCE: unsafe scratch')
    if out.exists():verified(out,source,size);return size
    part=out.with_suffix(out.suffix+'.part')
    check=out.with_suffix(out.suffix+'.checkpoint.json')
    stamp={k:source[k] for k in ('source_id','language','dataset_version','source_sha256','url','identity')}
    stamp['size']=size
    if part.is_symlink() or check.is_symlink():raise Blocked('BLOCKED_SOURCE: unsafe scratch')
    if part.exists() or check.exists():
        if (not part.is_file() or not check.is_file() or json.loads(check.read_text())!=stamp
                or part.stat().st_size>=size):raise Blocked('BLOCKED_SOURCE: stale checkpoint')
    else:atomic(check,stamp)
    for trial in range(1,attempts+1):
        offset=part.stat().st_size if part.exists() else 0
        conn=None
        try:
            conn=PublicHTTPS(source['host'],timeout=40,context=ssl.create_default_context())
            headers={'Accept-Encoding':'identity','User-Agent':'public-source-snapshots/1'}
            if offset:headers['Range']=f'bytes={offset}-{size-1}'
            conn.request('GET',target,headers=headers)
            response=conn.getresponse()
            hdr={k.lower():v for k,v in response.getheaders()}
            if (response.status!=(206 if offset else 200)
                    or hdr.get('content-encoding','identity')!='identity'
                    or 'transfer-encoding' in hdr or hdr.get('content-length')!=str(size-offset)
                    or (offset and hdr.get('content-range')!=f'bytes {offset}-{size-1}/{size}')):
                raise Blocked('BLOCKED_SOURCE: redirect/incorrect range/length')
            count=offset
            with part.open('ab' if offset else 'wb') as dst:
                while count<size:
                    b=response.read(min(CHUNK,size-count))
                    if not b:raise OSError('truncated response')
                    dst.write(b);count+=len(b)
                if response.read(1):raise Blocked('BLOCKED_SOURCE: extra source bytes')
                dst.flush();os.fsync(dst.fileno())
            verified(part,source,size)
            os.replace(part,out);check.unlink()
            return size
        except Blocked:raise
        except (OSError,http.client.HTTPException,ssl.SSLError):
            if trial==attempts:raise Blocked('BLOCKED_SOURCE: download retries exhausted')
            delay(2**trial)
        finally:
            if conn:conn.close()

def partitions(path,source,out,size,fmt='jsonl',shard_rows=10000,max_expand=16*1024**3):
    """Ephemeral source-bound shards; never a release or a queue acceptance."""
    verified(path,source,size)
    if (fmt not in FORMATS or type(shard_rows)!=int or not 1<=shard_rows<=10000
            or type(max_expand)!=int or not 0<max_expand<=16*1024**3):
        raise Blocked('BLOCKED_SOURCE: invalid format/shard budget')
    out=Path(out)
    if out.is_symlink():raise Blocked('BLOCKED_SOURCE: output symlink')
    if out.exists():
        receipt=out/'receipt.json'
        if receipt.is_symlink() or not receipt.is_file():raise Blocked('BLOCKED_SOURCE: partial directory')
        result=json.loads(receipt.read_text())
        if not isinstance(result,dict):raise Blocked('BLOCKED_SOURCE: invalid receipt')
        counters=('real_input_rows','accepted_rows','rejected_rows')
        if (not all(type(result.get(k)) is int and result[k]>=0 for k in counters)
                or result['real_input_rows']!=result['accepted_rows']+result['rejected_rows']):
            raise Blocked('BLOCKED_SOURCE: invalid receipt counters')
        pieces=result.get('partitions')
        checkpoint=result.get('checkpoint')
        if (not isinstance(pieces,list) or not (1<=len(pieces)<=MAX_SHARDS)
                or not isinstance(checkpoint,dict)
                or checkpoint.get('source_sha256')!=source['source_sha256']
                or type(checkpoint.get('last_row')) is not int
                or checkpoint['last_row']!=result['real_input_rows']
                or type(checkpoint.get('last_shard')) is not int
                or checkpoint['last_shard']!=len(pieces)-1):
            raise Blocked('BLOCKED_SOURCE: invalid checkpoint')
        if (result.get('source_id')!=source['source_id'] or result.get('language')!=source['language']
                or result.get('dataset_version')!=source['dataset_version']
                or result.get('license_sha256')!=source['license_sha256']
                or result.get('license_id')!=source['license_id']
                or result.get('real_input_rows')!=result.get('accepted_rows',-1)+result.get('rejected_rows',-1)
                or result.get('source_sha256')!=source['source_sha256'] or result.get('input_bytes')!=size
                or result.get('format')!=fmt or result.get('shard_rows')!=shard_rows
                or result.get('status')!='STAGED_ONLY'):raise Blocked('BLOCKED_SOURCE: stale receipt')
        total_rows=0
        for i,entry in enumerate(pieces):
            if (not isinstance(entry,dict) or entry.get('name')!=f'part-{i:08d}.jsonl'
                    or entry.get('index')!=i or type(entry.get('rows')) is not int
                    or not 1<=entry['rows']<=shard_rows
                    or entry.get('source_sha256')!=source['source_sha256']
                    or entry.get('language')!=source['language']
                    or not SHA.fullmatch(str(entry.get('sha256','')))
                    or (out/entry['name']).is_symlink() or sha_file(out/entry['name'])!=entry['sha256']):
                raise Blocked('BLOCKED_SOURCE: modified shard')
            total_rows+=entry['rows']
        if total_rows!=result['accepted_rows']:
            raise Blocked('BLOCKED_SOURCE: shard row count mismatch')
        if (out/'rejects.jsonl').is_symlink() or sha_file(out/'rejects.jsonl')!=result['rejects_sha256']:
            raise Blocked('BLOCKED_SOURCE: changed rejects')
        return result
    if not out.parent.is_dir() or out.is_symlink():raise Blocked('BLOCKED_SOURCE: output parent')
    if shutil.disk_usage(out.parent).free<min(max_expand,size*2):
        raise Blocked('BLOCKED_SOURCE: disk budget')
    # mkdir is atomic across concurrent jobs. An interrupted reservation remains
    # visibly incomplete and is never mistaken for verified output.
    try:out.mkdir()
    except FileExistsError as exc:raise Blocked('BLOCKED_SOURCE: concurrent partition') from exc
    temp=Path(tempfile.mkdtemp(prefix='.snapshot-stage-',dir=out.parent))
    parts=[];real=accepted=rejected=expanded=0;writer=None;part_hash=None;part_n=0
    try:
        with FORMATS[fmt](path,'rb') as stream, (temp/'rejects.jsonl').open('wb') as reject_stream:
            while True:
                raw=stream.readline(1048577)
                if not raw:break
                real+=1;expanded+=len(raw)
                if expanded>max_expand or len(raw)>MAX_LINE:
                    raise Blocked('BLOCKED_SOURCE: decompression/line limit')
                reason=None
                if not raw.endswith(b'\n') or b'\0' in raw or raw.startswith(b'\xef\xbb\xbf'):
                    reason='framing'
                else:
                    try:
                        row=json.loads(raw.decode('utf-8','strict'),parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
                        if not isinstance(row,dict) or row.get('lang_code')!=source['language']:
                            reason='language'
                        else:
                            try:
                                admission.extract(row,source['language'],source['license_id'],
                                                  source['source_id'],source['script'],real)
                            except admission.AdmissionError:
                                reason='lexical_admission'
                    except (ValueError,UnicodeError):reason='invalid_json_utf8'
                if reason:
                    rejected+=1
                    reject_stream.write(encode({'source_line':real,'line_sha256':hashlib.sha256(raw).hexdigest(),'reason':reason}))
                    continue
                if writer is None:
                    if len(parts)>=MAX_SHARDS:raise Blocked('BLOCKED_SOURCE: shard count')
                    name=f'part-{len(parts):08d}.jsonl'
                    writer=(temp/name).open('wb');part_hash=hashlib.sha256();part_n=0
                writer.write(raw);part_hash.update(raw);part_n+=1;accepted+=1
                if part_n==shard_rows:
                    writer.flush();os.fsync(writer.fileno());writer.close();writer=None
                    parts.append({'name':name,'index':len(parts),'rows':part_n,
                                  'sha256':part_hash.hexdigest(),'source_sha256':source['source_sha256'],
                                  'language':source['language']})
        if writer is not None:
            writer.flush();os.fsync(writer.fileno());writer.close();writer=None
            parts.append({'name':name,'index':len(parts),'rows':part_n,
                          'sha256':part_hash.hexdigest(),'source_sha256':source['source_sha256'],
                          'language':source['language']})
        if not accepted:raise Blocked('BLOCKED_SOURCE: no accepted corpus rows')
        result={'schema_version':'1.0','status':'STAGED_ONLY','publication_approved':False,
                'source_id':source['source_id'],'language':source['language'],
                'dataset_version':source['dataset_version'],'source_sha256':source['source_sha256'],
                'license_id':source['license_id'],'license_sha256':source['license_sha256'],
                'input_bytes':size,'expanded_bytes':expanded,'format':fmt,'shard_rows':shard_rows,
                'real_input_rows':real,'accepted_rows':accepted,'rejected_rows':rejected,
                'partitions':parts,'rejects_sha256':sha_file(temp/'rejects.jsonl'),
                'checkpoint':{'source_sha256':source['source_sha256'],'last_row':real,'last_shard':len(parts)-1}}
        atomic(temp/'receipt.json',result)
        # Replace only our own empty reserved directory; other workers cannot
        # create or silently overwrite a partition at this output path.
        os.replace(temp,out)
        return result
    except (OSError,EOFError,lzma.LZMAError) as error:
        raise Blocked('BLOCKED_SOURCE: damaged compressed input or disk write') from error
    finally:
        if writer is not None:writer.close()
        if temp.exists():shutil.rmtree(temp)

def queue_ready():
    from tools.gha_factory.dispatcher import queue
    return 'source_snapshot' in queue.TASK_TYPES

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=('readiness','stage-local'))
    p.add_argument('--repo-root',type=Path,default=Path.cwd())
    p.add_argument('--source-id',required=True)
    p.add_argument('--language',required=True)
    p.add_argument('--dataset-version',required=True)
    p.add_argument('--expected-size',type=int,required=True)
    p.add_argument('--snapshot',type=Path)
    p.add_argument('--output',type=Path)
    p.add_argument('--format',choices=sorted(FORMATS),default='jsonl')
    p.add_argument('--shard-rows',type=int,default=10000)
    a=p.parse_args(argv)
    try:
        source=approved(a.repo_root,a.source_id,a.language,a.dataset_version)
        if a.mode=='readiness':
            if not queue_ready():raise Blocked('BLOCKED_DEPENDENCY_GHA02: no snapshot lease/checkpoint API')
            raise Blocked('BLOCKED_DEPENDENCY_GHA02: no approved ingestion handoff API')
        if not a.snapshot or not a.output or not a.snapshot.is_absolute() or not a.output.is_absolute():
            raise Blocked('BLOCKED_SOURCE: absolute scratch paths required')
        result=partitions(a.snapshot,source,a.output,a.expected_size,fmt=a.format,shard_rows=a.shard_rows)
        print(json.dumps({k:result[k] for k in ('source_sha256','real_input_rows','accepted_rows','rejected_rows')}))
        return 0
    except (Blocked,OSError,EOFError,gzip.BadGzipFile,lzma.LZMAError) as e:
        print(json.dumps({'status':'BLOCKED','reason':str(e)}));return 2

if __name__=='__main__':
    raise SystemExit(main())
