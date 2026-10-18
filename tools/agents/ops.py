"""Operational agents: repair, janitor, watchdog, docs, gaps, guards.

They read versioned files and tolerate absence. None call a paid API.
"""

import ast
import re
from pathlib import Path

from tools.agents.common import SCHEMA_VERSION, load_json_tolerant
from tools.agents.roster import ROSTER

PROTECTED_BRANCHES = frozenset({'main', 'master', 'agents/data', 'gh-pages'})
CLEANABLE_PREFIXES = ('language-production/', 'agents/tmp/')
BOT_BRANCH_PREFIXES = ('cursor/', 'agents/', 'language-production/')
ISSUE_RULES = (
    ('harvest', ('wikidata', 'kaikki', 'tatoeba', 'harvest')),
    ('legal', ('license', 'copyright', 'attribution')),
    ('qa', ('quarantine', 'content policy')),
    ('packs', ('pack', 'manifest', 'sqlite')),
    ('coverage', ('coverage', 'status')),
)


def janitor_action(pr):
    """Decide one pull-request action. The caller performs git; this does not."""
    if not isinstance(pr, dict):
        return 'leave', 'malformed'
    branch = pr.get('branch') or ''
    if not branch.startswith(BOT_BRANCH_PREFIXES):
        return 'leave', 'not a bot branch'
    if pr.get('draft'):
        return 'leave', 'draft'
    # An unverified review state must never be treated as resolved.
    if pr.get('unresolved') is not False:
        return 'leave', 'unverified or unresolved review'
    if pr.get('merge_state') not in ('CLEAN', 'BEHIND'):
        return 'leave', 'merge state not verified clean'
    checks = pr.get('checks') or []
    if not checks or any(item.get('status') != 'completed' for item in checks):
        return 'leave', 'checks incomplete'
    if any(item.get('conclusion') not in ('success', 'skipped') for item in checks):
        return 'leave', 'checks failed'
    gate = any(
        item.get('name') == 'public-pr-merge-gate' and item.get('conclusion') == 'success'
        for item in checks
    )
    if not gate:
        return 'leave', 'merge gate has not passed'
    if pr.get('behind'):
        return 'update', 'merge main into the branch without force push'
    return 'merge', 'required checks are green'


def unresolved_review_threads(payload):
    """True if GitHub's exact PR review thread state is unsafe or unknown."""
    try:
        if payload.get('errors'):
            return True
        threads = payload['data']['repository']['pullRequest']['reviewThreads']
        nodes = threads['nodes']
        page = threads['pageInfo']
        if not isinstance(nodes, list) or not isinstance(page.get('hasNextPage'), bool):
            return True
        return page['hasNextPage'] or any(
            not isinstance(node, dict) or node.get('isResolved') is not True
            for node in nodes
        )
    except (AttributeError, KeyError, TypeError):
        return True


def duplicate_issues(issues):
    """Newer open issues with the same title are duplicates. The oldest stays."""
    groups = {}
    for issue in issues or []:
        if not isinstance(issue, dict) or issue.get('state') not in (None, 'open'):
            continue
        title = issue.get('title') or ''
        groups.setdefault(title, []).append(issue)
    close = []
    for title, rows in groups.items():
        if not title or len(rows) < 2:
            continue
        ordered = sorted(rows, key=lambda row: row.get('number') or 0)
        close.extend(ordered[1:])
    return close


def agent_for_issue(title):
    text = (title or '').casefold()
    for name, words in ISSUE_RULES:
        if any(word in text for word in words):
            return name
    return 'coverage'


def stale_heartbeats(heartbeats, now_epoch, max_age_seconds):
    """Missing or old heartbeats. Malformed timestamps count as stale, not fatal."""
    stale = []
    known = {row.get('name'): row for row in heartbeats or [] if isinstance(row, dict)}
    for agent in ROSTER:
        row = known.get(agent['name'])
        if not row:
            stale.append(agent['name'])
            continue
        stamp = row.get('last_run') or ''
        try:
            from datetime import datetime
            parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00') )
            age = now_epoch - parsed.timestamp()
        except (TypeError, ValueError):
            stale.append(agent['name'])
            continue
        if age > max_age_seconds:
            stale.append(agent['name'])
    return stale


def dispatch_batch(stale, cap=3):
    return list(stale or [])[:cap]


def branch_deletable(name, merged):
    if not isinstance(name, str) or not name or name in PROTECTED_BRANCHES:
        return False
    if name.startswith('cursor/'):
        return False
    if not name.startswith(CLEANABLE_PREFIXES):
        return False
    return bool(merged)


def untested_modules(tool_root, test_roots):
    """Modules whose name never appears in a test file. This does not write tests."""
    tool_root = Path(tool_root)
    names = []
    if not tool_root.is_dir():
        return names
    mentioned = ''
    for root in test_roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for path in root.rglob('*.py'):
            try:
                mentioned += '\n' + path.read_text(encoding='utf-8')
            except (OSError, UnicodeError):
                continue
    for path in tool_root.rglob('*.py'):
        if path.name.startswith('test_') or path.name == '__init__.py':
            continue
        module = path.stem
        if module not in mentioned and f'{path.parent.name}.{module}' not in mentioned:
            names.append(str(path))
    return sorted(names)


def schema_guard(constants):
    """Warn when the v2 contract is absent. Do not fail because packs are missing."""
    constants = constants or {}
    problems = []
    warnings = []
    if constants.get('user_version') not in (None, 2) and constants.get('contract') != '1.0.0':
        problems.append('unexpected sqlite contract')
    if not constants.get('ddl'):
        warnings.append('DDL text was not loaded')
    if not constants.get('packs_present'):
        warnings.append('no root packs are published; that is expected')
    return {'schema_version': SCHEMA_VERSION, 'problems': problems, 'warnings': warnings}


def performance_report(current, previous):
    current = current or {}
    previous, warning = load_json_tolerant_bytes(previous)
    flags = []
    if warning:
        flags.append('previous snapshot ' + warning)
    prev_bytes = (previous or {}).get('bytes') or {}
    for name, size in (current.get('bytes') or {}).items():
        old = prev_bytes.get(name)
        if isinstance(old, int) and old > 0 and isinstance(size, int) and size > old * 1.25:
            flags.append(f'{name} grew by more than 25%')
    return {
        'schema_version': SCHEMA_VERSION,
        'bytes': current.get('bytes') or {},
        'flags': flags,
    }


def load_json_tolerant_bytes(previous):
    if previous is None:
        return {}, 'missing'
    if isinstance(previous, dict):
        if previous.get('schema_version') != SCHEMA_VERSION:
            return {}, 'stale_or_malformed'
        return previous, ''
    return load_json_tolerant(previous, {'schema_version': SCHEMA_VERSION, 'bytes': {}})


def docs_check(root):
    root = Path(root)
    missing = []
    for agent in ROSTER:
        workflow = root / agent['workflow']
        if not workflow.is_file():
            missing.append(agent['workflow'])
            continue
        text = workflow.read_text(encoding='utf-8')
        if 'workflow_dispatch' not in text:
            missing.append(agent['workflow'] + ':no-dispatch')
        for cron in agent['crons']:
            if cron not in text:
                missing.append(agent['workflow'] + ':' + cron)
        if 'permissions:' not in text:
            missing.append(agent['workflow'] + ':no-permissions')
        if 'cancel-in-progress: false' not in text:
            missing.append(agent['workflow'] + ':cancel')
    return {'schema_version': SCHEMA_VERSION, 'missing': missing, 'agents': len(ROSTER)}


def python_syntax_ok(path):
    try:
        ast.parse(Path(path).read_text(encoding='utf-8'))
    except (OSError, SyntaxError, UnicodeError):
        return False
    return True


URL_RE = re.compile(r'^https://[^\s]+$')


def urls_well_formed(urls):
    bad = [url for url in urls or [] if not isinstance(url, str) or not URL_RE.match(url)]
    return bad
