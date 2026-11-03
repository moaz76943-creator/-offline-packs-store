#!/usr/bin/env python3
"""Main-only controller/worker/finalizer compatibility entry point."""
import argparse
import json
import os
from pathlib import Path
from tools.gha_factory.dispatcher import controller as legacy, queue
from . import api, engine

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('controller')
    worker=sub.add_parser('worker')
    worker.add_argument('--issue',required=True,type=int)
    worker.add_argument('--task-id',required=True)
    worker.add_argument('--out',type=Path,required=True)
    final=sub.add_parser('finalize');final.add_argument('--artifacts',type=Path,required=True)
    args=parser.parse_args(argv)
    if os.getenv('GITHUB_REPOSITORY')!=engine.REPO or os.getenv('GITHUB_REF')!='refs/heads/main' or os.getenv('GITHUB_EVENT_NAME') not in ('schedule','workflow_dispatch'):
        parser.error('canonical main schedule/manual only')
    run_id=int(os.environ['GITHUB_RUN_ID']);attempt=int(os.environ['GITHUB_RUN_ATTEMPT'])
    if run_id<=0 or attempt<=0:parser.error('invalid run identity')
    gh=api.GitHub();now=queue.utc_now()
    if args.command=='controller':
        ctx,sha=legacy.context();seeded=engine.seed(gh,ctx,sha,legacy.ROOT)
        telemetry={}
        jobs=engine.control(gh,run_id,attempt,now,legacy.ROOT,ctx,sha,telemetry=telemetry)
        with open(os.environ['GITHUB_OUTPUT'],'a') as out:
            out.write('jobs='+json.dumps({'include':jobs},separators=(',',':'))+'\n')
            out.write('has_work='+str(bool(jobs)).lower()+'\n')
        source_admission=('BLOCKED_BY_SOURCE_ADMISSION' if not ctx['sources']
                          else 'ADMISSION_CHECK_REQUIRED')
        states=telemetry.get('task_states',{})
        if jobs:
            queue_status='CLAIMED'
            work_status='WORK_CLAIMED'
        else:
            queue_status=('BROKEN_QUEUE' if telemetry.get('malformed_queue_issues',0)>0
                          else 'EMPTY_QUEUE' if telemetry.get('queue_total',0)==0
                          else 'ACTIVE_WORK_ONLY' if any(states.get(s,0) for s in ('CLAIMED','RUNNING'))
                          else 'NO_ELIGIBLE_TASKS')
            work_status=('BROKEN_QUEUE' if queue_status=='BROKEN_QUEUE'
                         else source_admission if source_admission=='BLOCKED_BY_SOURCE_ADMISSION'
                         else 'SUCCESS_NO_WORK')
        print(json.dumps({'run_id':run_id,'run_attempt':attempt,'seeded':seeded,
                          'stage':'controller','claimed':len(jobs),
                          'queue_status':queue_status,'task_states':states,
                          'malformed_queue_issues':telemetry.get('malformed_queue_issues',0),
                          'source_admission':source_admission,
                          'work_status':work_status,
                          'production_publication':False}))
    elif args.command=='worker':
        result=engine.execute(gh,args.issue,args.task_id,run_id,attempt,args.out,legacy.ROOT,now)
        print(json.dumps(result));return int(result['status']=='FAILED')
    else:
        raw=os.environ.get('JOBS_JSON','')
        if len(raw)>4096:raise ValueError('oversized matrix')
        try:
            result=engine.finalize(gh,json.loads(raw)['include'],args.artifacts,run_id,attempt,now)
        except engine.FinalizationError as exc:
            print(json.dumps({'results':exc.results,'errors':exc.errors}))
            return 1
        print(json.dumps(result))
    return 0

if __name__=='__main__':raise SystemExit(main())
