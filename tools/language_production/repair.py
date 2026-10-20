"""Deterministic repair plans. At most two attempts for one failure signature."""

MAX_ATTEMPTS = 2
MIN_SLICE_BYTES = 1048576


def plan_repair(signature, attempts):
    """Return the next action. After two attempts the signature is recorded and work continues."""
    attempts = int(attempts or 0)
    text = (signature or '').casefold()
    if attempts >= MAX_ATTEMPTS:
        return {'action': 'record-and-continue', 'attempts': attempts, 'signature': signature}
    retry = ('timeout', 'http', '206', 'range', 'max-filesize', 'curl')
    cache = ('gzip', 'corrupt', 'checksum', 'zlib')
    record = ('json', 'malformed', 'utf-8')
    if any(token in text for token in retry):
        return {
            'action': 'retry-smaller-slice',
            'max_bytes_factor': 0.5,
            'attempts': attempts + 1,
            'signature': signature,
        }
    if any(token in text for token in cache):
        return {'action': 'clear-cache', 'attempts': attempts + 1, 'signature': signature}
    if any(token in text for token in record):
        return {'action': 'skip-quarantine-record', 'attempts': attempts + 1, 'signature': signature}
    return {'action': 'record-and-continue', 'attempts': attempts, 'signature': signature}


def note_failure(state, signature):
    """Remember one attempt. A pending factor shrinks the next slice after a transfer failure."""
    state = dict(state or {})
    attempts = dict(state.get('attempts') or {})
    plan = plan_repair(signature, attempts.get(signature, 0))
    attempts[signature] = plan['attempts']
    state['attempts'] = attempts
    state['pending_factor'] = plan.get('max_bytes_factor', 1)
    state['last_action'] = plan['action']
    state['last_signature'] = signature
    return state, plan


def note_success(state):
    state = dict(state or {})
    state['pending_factor'] = 1
    state['last_action'] = 'ok'
    return state


def slice_budget(max_bytes, state, floor=MIN_SLICE_BYTES):
    factor = 1
    if isinstance(state, dict):
        pending = state.get('pending_factor', 1)
        if isinstance(pending, (int, float)) and 0 < pending <= 1:
            factor = pending
    budget = int(int(max_bytes) * factor)
    return max(int(floor), budget)


def should_advance(success, plan):
    """Leave the cursor in place for a retry. Move on after success or a recorded failure."""
    if success:
        return True
    return bool(plan) and plan.get('action') == 'record-and-continue'
