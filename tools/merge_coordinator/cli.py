"""Actions entrypoint: evidence first, armed single merge only."""
import argparse,collections,hashlib,json,os,sys,time
from pathlib import Path
from .github_extra import GitHub
from .transport import APIError
from .inventory import collect
from .classification import classify
from .engine import Coordinator,MergeIncident

def competing_writer(api):
    """Existing alternate writer blocks this coordinator, including unknown API errors."""
    try:
        api.call('/contents/.github/workflows/public_merge_coordinator.yml')
    except APIError as exc:
        return exc.status != 404
    except Exception:
        return True
    return True

def main(argv=None,api=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--output',default='merge-status.json')
    args=parser.parse_args(argv)
    api=api or GitHub(os.getenv('GITHUB_REPOSITORY','moaz76943-creator/-offline-packs-store'))
    started=time.time()
    sha=api.head()
    protection=api.protection()
    prs,merged,complete,failures=collect(api,protection)
    decisions=classify(prs,main_sha=sha,protection=protection,
                       merged=merged,completeness=complete)
    counts=dict(sorted(collections.Counter(x.state for x in decisions).items()))
    armed=(args.apply and os.getenv('SMART_MERGE_ENABLED')=='true'
        and bool(os.getenv('GITHUB_RUN_ID'))
        and os.getenv('GITHUB_WORKFLOW')=='Smart PR Merge Coordinator'
        and os.getenv('GITHUB_EVENT_NAME') in ('schedule','workflow_dispatch','workflow_run'))
    mode='ARMED' if armed else 'DRY_RUN'
    incident=None
    action=None
    receipt_failures=[]
    if api.checks(sha).get('validate')!='success':
        incident='main_push_validate_not_success'
    if not complete:
        incident='incomplete_pr_inventory'
    if os.getenv('SMART_MERGE_CODE_SHA') and os.getenv('SMART_MERGE_CODE_SHA')!=sha:
        incident='checkout_main_sha_stale'
    if competing_writer(api):
        incident='competing_authoritative_writer_present_or_unverifiable'
    if armed and not incident:
        for d in decisions[:20]:
            digest=hashlib.sha256(json.dumps([d.state,d.reasons,d.head],
                                 sort_keys=True).encode()).hexdigest()[:16]
            try:
                api.record(d.number,f'smart-merge-decision:{d.number}:{digest}',
                           {'main_sha':sha,**d.json()})
            except (APIError,TimeoutError,OSError) as err:
                receipt_failures.append({'pr':d.number,'reason':str(err)[:160]})
        chosen=next((d for d in decisions if d.state=='VERIFIED_READY'),None)
        if chosen:
            original=next(p for p in prs if p.number==chosen.number)
            signature={(p.number,p.head) for p in prs}
            try:
                action=Coordinator(api).integrate(original,main_sha=sha,
                            protection=protection,lease=True,inventory=signature)
                if action['status']=='MERGED':
                    try:
                        api.record(original.number,
                            f'smart-merge-success:{sha}:{original.head}',action)
                    except (APIError,TimeoutError,OSError) as err:
                        receipt_failures.append({'pr':original.number,'reason':str(err)[:160]})
            except MergeIncident as err:
                incident='post_merge_incident:'+str(err)
            except (APIError,TimeoutError,OSError) as err:
                action={'status':'RETRY_LATER','reason':str(err)[:160]}
    result={'schema_version':1,'source':'github-live','main_sha':sha,
        'mode':mode,'protection':protection,'inventory_complete':complete,
        'total_prs':len(prs),'counts':counts,'decisions':[d.json() for d in decisions],
        'inventory_errors':failures,'incident_stop':incident,
        'merge_action':action,'receipt_failures':receipt_failures,
        'elapsed_seconds':round(time.time()-started,2)}
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2,
                                 sort_keys=True)+'\n',encoding='utf-8')
    summary=['# تقرير منسق الدمج الذكي',
             f'- الوضع: {mode}',f'- main: {sha}',f'- PRs: {len(prs)}',
             f'- التصنيفات: {counts}',f'- العائق: {incident or "لا يوجد"}',
             f'- الدمج: {action or "لم يحاول"}']
    Path('merge-summary.md').write_text('\n'.join(summary)+'\n',encoding='utf-8')
    print('\n'.join(summary))
    return 1 if incident and armed else 0

if __name__=='__main__':
    sys.exit(main())
