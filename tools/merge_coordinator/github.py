"""Read-only verification adapter for source evidence."""
from .transport import Transport,APIError

class GitHub(Transport):
    def head(self):
        return self.call('/branches/main')['commit']['sha']

    def protection(self):
        if not self.call('/branches/main').get('protected'):
            return {'enforce':False,'reason':'main_not_protected'}
        try:
            p=self.call('/branches/main/protection')
        except APIError as err:
            return {'enforce':False,'reason':f'protection_unreadable_{err.status}'}
        checks=p.get('required_status_checks') or {}
        reviews=p.get('required_pull_request_reviews') or {}
        contexts=set(checks.get('contexts') or [])
        contexts.update(x.get('context') for x in checks.get('checks',[]) if x.get('context'))
        return {
            'enforce':True,'strict':checks.get('strict') is True,
            'required':bool(contexts),'contexts':sorted(contexts),
            'reviews':reviews.get('required_approving_review_count') or 0,
            'no_bypass':((p.get('enforce_admins') or {}).get('enabled') is True
                and (p.get('allow_force_pushes') or {}).get('enabled') is False
                and (p.get('allow_deletions') or {}).get('enabled') is False),
            'reason':'verified_rest_protection'
        }

    def checks(self,sha):
        data=self.call(f'/commits/{sha}/check-runs?per_page=100')
        if data.get('total_count',0)>100:
            raise APIError(0,'Incomplete checks')
        found={x['name']:(x.get('conclusion') if x.get('status')=='completed' else 'pending')
               for x in data.get('check_runs',[])}
        for x in self.call(f'/commits/{sha}/status').get('statuses',[]):
            found.setdefault(x['context'],x.get('state','pending'))
        return found
