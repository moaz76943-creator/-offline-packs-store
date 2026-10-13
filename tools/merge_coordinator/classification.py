"""Every open PR receives exactly one conservative operational state."""
from .policy import STATES, SKIP, Decision, graph, high_risk

def classify(prs, *, main_sha, protection=None, merged=None, completeness=True):
    merged=set(merged or ())
    conflicts,deps=graph(prs)
    result=[]
    safe=bool(protection and protection.get('enforce') and protection.get('strict')
        and protection.get('required') and protection.get('reviews',0)>=1
        and protection.get('no_bypass')
        and 'public-pr-merge-gate' in protection.get('contexts',[]))
    for p in sorted(prs,key=lambda p:p.number):
        missing=sorted(deps[p.number]-merged)
        overlap=sorted(conflicts[p.number])
        if p.draft:
            state,reason='DRAFT','draft_requires_authorized_completion_and_review'
        elif SKIP.search(p.head_message):
            state,reason='BLOCKED_SKIP_CI','exact_head_suppresses_ci'
        elif p.mergeable is False or p.mergeable_state=='dirty':
            state,reason='MERGE_CONFLICT','github_reports_conflict'
        elif missing:
            state,reason='DEPENDENCY_BLOCKED','unmerged_prerequisites:'+str(missing)
        elif high_risk(p.files):
            state,reason=high_risk(p.files),'independent_review_required'
        elif overlap:
            exact=sorted(o.number for o in prs if o.number in overlap and o.head==p.head and o.files==p.files)
            if exact and p.number>min(exact):
                state,reason='DUPLICATE','exact_sha_duplicate_of:'+str(min(exact))
            else:
                state,reason='SEMANTIC_CONFLICT','file_ownership_overlap_requires_reconciliation'
        elif not completeness or not p.files or not p.head_message or not main_sha or p.base!=main_sha:
            state,reason='UNVERIFIED','incomplete_or_stale_live_metadata'
        elif not safe:
            state,reason='UNVERIFIED','branch_protection_not_independently_verified'
        elif p.mergeable is not True or p.mergeable_state!='clean':
            state,reason='UNVERIFIED','mergeability_unconfirmed'
        elif p.change_requested or p.approvals<max(1,p.required_approvals):
            state,reason='HUMAN_REVIEW','fresh_approval_missing_or_vetoed'
        else:
            required=set(protection['contexts'])|set(p.required_checks)|{'public-pr-merge-gate'}
            missing_checks=sorted(c for c in required if c not in p.checks)
            pending=sorted(c for c in required if p.checks.get(c) in ('queued','in_progress','pending'))
            non_pass=sorted(c for c in required if c in p.checks and p.checks[c] not in ('success','queued','in_progress','pending'))
            if non_pass:
                state,reason='UNVERIFIED','failed_skipped_or_neutral_check:'+str(non_pass)
            elif missing_checks:
                state,reason='UNVERIFIED','missing_required_check:'+str(missing_checks)
            elif pending:
                state,reason='WAITING_CHECKS','pending_required_check:'+str(pending)
            else:
                state,reason='VERIFIED_READY','all_independent_gates_verified'
        assert state in STATES
        result.append(Decision(p.number,p.head,p.base,state,[reason],
                               sorted(deps[p.number]),overlap,len(p.files)))
    return result
