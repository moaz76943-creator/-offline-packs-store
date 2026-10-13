"""Bounded live PR inventory; failed evidence prevents any merge."""
from .policy import Pull
from .transport import APIError

def check_reviews(reviews,head,author):
    latest={}
    for x in reviews:
        user=(x.get('user') or {}).get('login')
        if user and user!=author and x.get('state') in ('APPROVED','CHANGES_REQUESTED','DISMISSED'):
            latest[user]=x
    approved=sum(x.get('state')=='APPROVED' and x.get('commit_id')==head
                 for x in latest.values())
    veto=any(x.get('state')=='CHANGES_REQUESTED' for x in latest.values())
    return approved,veto

def collect(api,protection):
    items=api.pages('/pulls?state=open')
    prs=[]
    failures=[]
    merged=set()
    for item in items:
        number=item['number']
        try:
            d=api.pr(number)
            sha=d['head']['sha']
            files=tuple(x['filename'] for x in api.changed_files(number))
            commit=api.commit(sha)
            approvals,veto=check_reviews(api.reviews(number),sha,d['user']['login'])
            checks=api.checks(sha)
            prs.append(Pull(number=number,head=sha,base=d['base']['sha'],
                draft=d['draft'],files=files,mergeable=d.get('mergeable'),
                mergeable_state=d.get('mergeable_state') or '',
                head_message=commit['commit']['message'],
                body=d.get('body') or '',title=d['title'],
                checks=checks,approvals=approvals,
                required_approvals=max(1,protection.get('reviews',1)),
                change_requested=veto,author=d['user']['login'],
                labels=tuple(x['name'] for x in d.get('labels',[]))))
        except (APIError,KeyError,ValueError,TypeError) as err:
            failures.append({'pr':number,'reason':str(err)[:300]})
            prs.append(Pull(number=number,
                 head=(item.get('head') or {}).get('sha',''),
                 base=(item.get('base') or {}).get('sha',''),
                 draft=item.get('draft',True)))
    for p in prs:
        for dep in p.dependencies:
            if dep in merged:
                continue
            try:
                if api.pr(dep).get('merged_at'):
                    merged.add(dep)
            except (APIError,KeyError,TypeError):
                pass
    return prs,merged,not failures,failures
