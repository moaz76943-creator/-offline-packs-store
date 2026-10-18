"""Sentences stay empty until the owner approves the sentence source."""

import re

OWNER = 'moaz76943-creator'
APPROVAL = re.compile(r'(?m)^decision:\s*approve\s*$', re.IGNORECASE)
TATOEBA_ISSUE_TITLE = 'Source decision: Tatoeba'
WIKIDATA_ISSUE_TITLE = 'Source decision: Wikidata Lexemes'


REQUIRED_ISSUES = (TATOEBA_ISSUE_TITLE, WIKIDATA_ISSUE_TITLE)


def missing_issue_titles(existing):
    """Titles that still need an owner-decision issue. Matching is exact."""
    have = {title for title in (existing or []) if isinstance(title, str)}
    return [title for title in REQUIRED_ISSUES if title not in have]


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
