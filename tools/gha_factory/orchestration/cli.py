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
        jobs=engine.control(gh,run_id,attempt,now,legacy.ROOT,ctx,sha)
        with open(os.environ['GITHUB_OUTPUT'],'a') as out:
            out.write('jobs='+json.dumps({'include':jobs},separators=(',',':'))+'\n')
            out.write('has_work='+str(bool(jobs)).lower()+'\n')
        print(json.dumps({'run_id':run_id,'run_attempt':attempt,'seeded':seeded,'claimed':len(jobs),'production_publication':False}))
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
