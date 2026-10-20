"""Shared contracts for independent agents. No network and no paid APIs."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = '1.0.0'
HEARTBEAT_VERSION = '1.0.0'
HALT_VALUES = ('true',)
PLACEHOLDERS = re.compile(
    r'^(?:todo|tbd|placeholder|lorem|ipsum|xxx+|n/?a|\?+|test|example|dummy|fixme)$',
    re.IGNORECASE,
)
SCRIPT_LETTERS = {
    'Latn': re.compile(r'[A-Za-z\u00C0-\u024F\u1E00-\u1EFF]'),
    'Arab': re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]'),
    'Hebr': re.compile(r'[\u0590-\u05FF]'),
    'Cyrl': re.compile(r'[\u0400-\u04FF]'),
    'Grek': re.compile(r'[\u0370-\u03FF]'),
    'Hans': re.compile(r'[\u4E00-\u9FFF]'),
    'Hant': re.compile(r'[\u4E00-\u9FFF]'),
    'Jpan': re.compile(r'[\u3040-\u30FF\u4E00-\u9FFF]'),
    'Kore': re.compile(r'[\uAC00-\uD7AF\u1100-\u11FF]'),
    'Hang': re.compile(r'[\uAC00-\uD7AF]'),
}
BLOCKED_CONCEPTS = frozenset({'Q154', 'Q11416', 'Q154136', 'Q11639'})
TRACE_KEYS = ('record_id', 'license_id', 'retrieval_date', 'source_id', 'language')


def halted(env=None):
    """True when either kill switch is exactly the string true."""
    env = env or {}
    for key in ('AGENTS_HALT', 'LANGUAGE_PRODUCTION_HALT'):
        if str(env.get(key) or '').strip().lower() in HALT_VALUES:
            return True
    return False


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def load_json_tolerant(path, default):
    """Return (value, warning). Missing, stale or malformed input never raises."""
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding='utf-8')
    except OSError:
        return default, 'missing'
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return default, 'malformed'
    if isinstance(default, dict):
        if not isinstance(data, dict):
            return default, 'malformed'
        if data.get('schema_version') != SCHEMA_VERSION:
            return default, 'stale_or_malformed'
    elif not isinstance(data, type(default)):
        return default, 'malformed'
    return data, ''


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def heartbeat(name, status, warning=''):
    return {
        'schema_version': SCHEMA_VERSION,
        'name': name,
        'last_run': utc_now(),
        'status': status,
        'version': HEARTBEAT_VERSION,
        'warning': warning or '',
    }


def write_heartbeat(directory, name, status, warning=''):
    payload = heartbeat(name, status, warning)
    write_json(Path(directory) / f'{name}.json', payload)
    return payload


def is_placeholder(text):
    value = (text or '').strip()
    return (not value) or bool(PLACEHOLDERS.fullmatch(value))


def script_matches(text, script):
    """Unknown scripts are not treated as a mismatch. A known script must appear."""
    pattern = SCRIPT_LETTERS.get(script or '')
    if pattern is None:
        return True
    return bool(pattern.search(text or ''))


def policy_qids(qids, blocked=BLOCKED_CONCEPTS):
    found = [qid for qid in (qids or []) if qid in blocked]
    if not found:
        return 'keep', ''
    if len(found) == len(list(qids or [])) or found:
        return 'exclude', 'blocked_concept'
    return 'quarantine', 'ambiguous_concept'


def row_traceable(row):
    if not isinstance(row, dict):
        return False
    if any(not isinstance(row.get(key), str) or not row.get(key).strip() for key in TRACE_KEYS):
        return False
    if is_placeholder(row.get('lemma') or row.get('text') or ''):
        return False
    return True
