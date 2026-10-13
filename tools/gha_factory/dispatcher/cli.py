#!/usr/bin/env python3
"""Commands for a serialized issue controller, read-only worker, and finalizer."""
import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
    from tools.gha_factory.dispatcher import controller,worker
else:
    from . import controller,worker


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('controller')
    work=sub.add_parser('worker')
    work.add_argument('--issue',type=int,required=True)
    work.add_argument('--task-id',required=True)
    work.add_argument('--out',type=Path,required=True)
    finish=sub.add_parser('finalize')
    finish.add_argument('--artifacts',type=Path,required=True)
    opts=parser.parse_args(argv)
    if os.environ.get('GITHUB_REPOSITORY')!=controller.REPO:
        parser.error('unexpected repository')
    run_id=int(os.environ['GITHUB_RUN_ID'])
    attempt=int(os.environ['GITHUB_RUN_ATTEMPT'])
    api=controller.GitHub()
    if opts.command=='controller':
        jobs=controller.controller(api,run_id,attempt)
        data={'include':jobs}
        with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as f:
            f.write('jobs='+json.dumps(data,separators=(',',':'))+'\n')
            f.write('has_work='+str(bool(jobs)).lower()+'\n')
        print(json.dumps({'claimed':len(jobs),'run_id':run_id,'run_attempt':attempt}))
    elif opts.command=='worker':
        if not opts.task_id or opts.issue<=0:parser.error('invalid issue/task')
        receipt=worker.worker(api,opts.issue,opts.task_id,run_id,attempt,opts.out)
        print(json.dumps({'status':receipt['status'],'task_id':receipt['task_id'],'run_id':run_id}))
        return 0 if receipt['status'] in ('SUCCEEDED','BLOCKED_SOURCE') else 1
    else:
        raw=os.environ.get('JOBS_JSON','')
        jobs=json.loads(raw)['include']
        results=controller.finish(api,jobs,opts.artifacts,run_id,attempt)
        print(json.dumps(results,sort_keys=True))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
