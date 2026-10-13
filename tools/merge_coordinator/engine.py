"""Expected-head squash merge engine. Never bypasses branch protection."""
from .classification import classify

class MergeIncident(RuntimeError):
    """Stop further merges; no destructive rollback."""

class Coordinator:
    def __init__(self,api):
        self.api=api

    def integrate(self,pr,*,main_sha,protection,lease,inventory=None):
        receipt={'pr':pr.number,'previous_main':main_sha,
                 'expected_head':pr.head,'new_main':None,'status':'NOT_READY'}
        if not lease:
            receipt['status']='NO_LEASE'
            return receipt
        if classify([pr],main_sha=main_sha,protection=protection)[0].state!='VERIFIED_READY':
            receipt['reason']='current_pr_not_verified'
            return receipt
        if self.api.head()!=main_sha:
            receipt['status']='STALE_MAIN'
            return receipt
        live=self.api.pr(pr.number)
        if live.get('state')!='open' or live.get('head',{}).get('sha')!=pr.head:
            receipt['status']='STALE_PR'
            return receipt
        if (live.get('draft') or live.get('mergeable') is not True
                or live.get('mergeable_state')!='clean'
                or live.get('base',{}).get('ref')!='main'):
            receipt['status']='NOT_READY'
            return receipt
        if self.api.protection()!=protection:
            receipt['status']='PROTECTION_CHANGED'
            return receipt
        from .inventory import check_reviews
        count,veto=check_reviews(self.api.reviews(pr.number),pr.head,pr.author)
        if veto or count<max(1,pr.required_approvals):
            receipt['status']='STALE_REVIEWS'
            return receipt
        if inventory is not None:
            try:
                fresh=self.api.pages('/pulls?state=open')
                signature={(x['number'],x['head']['sha']) for x in fresh}
            except Exception:
                receipt['status']='STALE_INVENTORY'
                return receipt
            if signature!=inventory:
                receipt['status']='STALE_INVENTORY'
                return receipt
        if self.api.checks(pr.head)!=pr.checks:
            receipt['status']='STALE_CHECKS'
            return receipt
        if self.api.head()!=main_sha:
            receipt['status']='STALE_MAIN'
            return receipt
        payload={'sha':pr.head,'merge_method':'squash',
                 'commit_title':f'Integrate verified PR #{pr.number}',
                 'commit_message':'Verified protected checks and expected PR head. No publication authorization.'}
        done=self.api.call(f'/pulls/{pr.number}/merge','PUT',payload)
        if not done.get('merged') or not done.get('sha'):
            receipt['status']='MERGE_REJECTED'
            return receipt
        receipt.update(status='MERGED',new_main=done['sha'])
        if self.api.head()!=done['sha']:
            raise MergeIncident('unexpected_main_after_merge')
        return receipt
