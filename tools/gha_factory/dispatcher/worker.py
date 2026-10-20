"""Read-only public admission-partition verification; no corpus publication."""
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from . import controller, queue


def work(t,out,root=controller.ROOT):
    ctx,registry_sha=controller.context(root)
    if queue.admission(t,ctx,registry_sha)!='READY':
        return ('BLOCKED_SOURCE',t['checkpoint'],0,None,'SOURCE_NOT_APPROVED')
    if t['task_type']=='registry_validate':
        result=subprocess.run([sys.executable,'catalog/validate_registry.py'],cwd=root,
                              capture_output=True,timeout=180,check=False)
        if result.returncode!=0:
            return ('FAILED',t['checkpoint'],0,None,'EXECUTION')
        return ('SUCCEEDED',1,0,None,None)
    if t['task_type']!='admission_partition_verify':
        return ('FAILED',t['checkpoint'],0,None,'INVALID_INPUT')
    approved=ctx['admissions'][(t['source_id'],t['language'],t['source_sha256'],t['shard'])]
    src=next(x for x in ctx['sources'] if x['source_id']==t['source_id'])
    path=(root/src['retrieval']['artifact_path']).resolve()
    module_file=root/'tools/gha_factory/admission/pipeline.py'
    spec=importlib.util.spec_from_file_location('canonical_source_admission',module_file)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.route05_source(root,t['source_id'],src['dataset_version'],path,'wiktextract-jsonl')
    except (OSError,ValueError,TypeError,KeyError):
        return ('BLOCKED_SOURCE',t['checkpoint'],0,None,'SOURCE_NOT_APPROVED')
    job=approved['job'];report=approved['report']
    if report.get('source_artifact_sha256')!=t['source_sha256'] or report.get('dataset_version')!=src['dataset_version']:
        return ('BLOCKED_SOURCE',t['checkpoint'],0,None,'SOURCE_CHANGED')
    partition=(approved['folder']/job['path']).resolve()
    if not partition.is_relative_to(approved['folder'].resolve()) or not partition.is_file() or partition.stat().st_size>40_000_000:
        return ('BLOCKED_SOURCE',t['checkpoint'],0,None,'INVALID_INPUT')
    count=0;sha=hashlib.sha256()
    with partition.open('rb') as stream:
        for raw in stream:
            count+=1
            if (count>queue.MAX_PARTITION_RECORDS or len(raw)>1_048_576
                    or not raw.endswith(b'\n')):
                return ('FAILED',t['checkpoint'],0,None,'INVALID_INPUT')
            sha.update(raw)
            item=json.loads(raw)
            if (not isinstance(item,dict) or item.get('source_id')!=t['source_id']
                    or item.get('language')!=t['language']
                    or item.get('dataset_version')!=src['dataset_version']
                    or item.get('source_artifact_sha256')!=t['source_sha256']):
                return ('FAILED',t['checkpoint'],0,None,'INVALID_INPUT')
    if count!=job['record_count'] or sha.hexdigest()!=job['sha256']:
        return ('BLOCKED_SOURCE',t['checkpoint'],0,None,'SOURCE_CHANGED')
    if t['checkpoint']>count:
        return ('FAILED',t['checkpoint'],0,None,'INVALID_INPUT')
    # This is a verification receipt, not a durable lexical release/acceptance.
    return ('SUCCEEDED',count,count-t['checkpoint'],None,None)


def worker(api,number,task_id,run_id,run_attempt,directory,root=controller.ROOT):
    issue=api.one(number)
    if not controller.owned_queue_issue(issue):
        raise ValueError('untrusted issue')
    t=queue.parse(issue.get('body'))
    if t['task_id']!=task_id or t['state']!='CLAIMED' or t['run_id']!=run_id or t['run_attempt']!=run_attempt:
        raise ValueError('worker lease mismatch')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    try:
        status,checkpoint,count,digest,error=work(t,directory,root)
    except (OSError,ValueError,TypeError,KeyError,subprocess.TimeoutExpired):
        status,checkpoint,count,digest,error='FAILED',t['checkpoint'],0,None,'EXECUTION'
    receipt={'schema_version':queue.VERSION,'task_id':t['task_id'],'run_id':run_id,
             'run_attempt':run_attempt,'status':status,'checkpoint':checkpoint,
             'candidate_count':count,'candidate_sha256':digest,'error_code':error}
    temp=directory/'receipt.tmp'
    temp.write_text(json.dumps(receipt,sort_keys=True,separators=(',',':')),encoding='utf-8')
    temp.replace(directory/'receipt.json')
    return receipt
