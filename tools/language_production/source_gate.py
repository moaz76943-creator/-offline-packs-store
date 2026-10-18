"""Owner chat decision of 2026-10-18 already covers the open redistributable sources.

A GitHub issue is not required for those sources. If one was opened, close it.
GPL, NC, ND and CC-BY-SA-3.0 stay blocked; this module cannot waive them.
"""

import re

OWNER = 'moaz76943-creator'
APPROVAL = re.compile(r'(?m)^decision:\s*approve\s*$', re.IGNORECASE)
DECISION_URL = 'https://cursor.com/agents/bc-7a06156e-03a6-58fc-aac5-03072971cf19'
DECISION_DATE = '2026-10-18'
TATOEBA_ISSUE_TITLE = 'Source decision: Tatoeba'
WIKIDATA_ISSUE_TITLE = 'Source decision: Wikidata Lexemes'
KAIKKI_ISSUE_TITLE = 'Source decision: Kaikki'
CHAT_APPROVED_TITLES = (
    TATOEBA_ISSUE_TITLE,
    WIKIDATA_ISSUE_TITLE,
    KAIKKI_ISSUE_TITLE,
)


def missing_issue_titles(existing):
    """No source-decision issue is required after the 2026-10-18 chat decision."""
    return []


def issues_to_close(existing):
    """Open decision issues for sources the owner already approved in chat."""
    have = {title for title in (existing or []) if isinstance(title, str)}
    return [title for title in CHAT_APPROVED_TITLES if title in have]


def owner_approved(comments, owner=OWNER):
    """True only when the owner wrote a line that is exactly `decision: approve`."""
    for comment in comments or []:
        if not isinstance(comment, dict):
            continue
        user = comment.get('user') or comment.get('login')
        if user != owner:
            continue
        body = comment.get('body') or ''
        if APPROVAL.search(body):
            return True
    return False
