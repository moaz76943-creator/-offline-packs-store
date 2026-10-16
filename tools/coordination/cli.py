"""Opt-in cross-run scope guard. No implicit bootstrap or protected-branch writes."""
import argparse
import json
import sys
from .leases import Coordinator, Denied, GhApi, GitRefStore, bootstrap_private_store


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--ledger-repo',required=True,help='PRIVATE coordination GitHub repository (never public)')
    sub=ap.add_subparsers(dest='command',required=True)
    init=sub.add_parser('bootstrap',help='explicitly create separate private coordination branch')
    inspect=sub.add_parser('inspect',help='read-only conflict check')
    inspect.add_argument('--repo',required=True)
    inspect.add_argument('--branch',required=True)
    inspect.add_argument('--path',action='append',required=True)
    claim=sub.add_parser('claim',help='attempt atomic remote scope claim')
    claim.add_argument('--repo',required=True)
    claim.add_argument('--branch',required=True)
    claim.add_argument('--sha',required=True)
    claim.add_argument('--path',action='append',required=True)
    claim.add_argument('--task',required=True)
    claim.add_argument('--owner',required=True)
    claim.add_argument('--ttl',type=int,default=900)
    claim.add_argument('--pr',type=int)
    claim.add_argument('--run-id',type=int)
    claim.add_argument('--run-attempt',type=int)
    for action in ('renew','release','recover','verify-pr'):
        parser=sub.add_parser(action)
        parser.add_argument('--task',required=True)
        parser.add_argument('--lease-id',required=True)
        if action!='recover':parser.add_argument('--owner',required=True)
        if action=='renew':parser.add_argument('--ttl',type=int,default=900)
        if action=='verify-pr':
            parser.add_argument('--pr',type=int,required=True)
            parser.add_argument('--head-sha',required=True)
    args=ap.parse_args(argv)
    try:
        api=GhApi()
        if args.command=='bootstrap':
            outcome={'status':'INITIALIZED','head_sha':bootstrap_private_store(api,args.ledger_repo)}
        else:
            store=GitRefStore(api,args.ledger_repo)
            coord=Coordinator(store,api)
            if args.command=='inspect':outcome=coord.inspect(args.repo,args.branch,args.path)
            elif args.command=='claim':
                outcome=coord.claim(args.task,args.repo,args.branch,args.sha,args.path,args.owner,
                    args.ttl,args.pr,args.run_id,args.run_attempt)
            elif args.command=='renew':outcome=coord.renew(args.task,args.lease_id,args.owner,args.ttl)
            elif args.command=='release':outcome=coord.release(args.task,args.lease_id,args.owner)
            elif args.command=='recover':outcome=coord.recover(args.task,args.lease_id)
            else:outcome=coord.verify_pr(args.task,args.lease_id,args.owner,args.pr,args.head_sha)
    except Denied as exc:
        outcome={'status':'BLOCKED','reason':str(exc)}
    print(json.dumps(outcome,ensure_ascii=False,sort_keys=True))
    return 0 if outcome.get('status') in ('READY','INITIALIZED','CLAIMED','RENEWED','RELEASED','RECOVERED','AUTHORIZED_SCOPE_ONLY') else 2


if __name__=='__main__':sys.exit(main())
