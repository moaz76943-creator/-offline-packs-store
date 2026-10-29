#!/usr/bin/env python3
"""
Queue Autoseed Manager for Content Factory.
Master Constitution Section 14 Compliant:
Scans legal/ledger/sources.json for APPROVED sources and seeds the factory queue,
preventing factory stalls when valid sources are documented.
"""
import json
import os
import sys

def autoseed_queue(sources_ledger_path: str, queue_output_path: str):
    if not os.path.exists(sources_ledger_path):
        return False, f"LEDGER_NOT_FOUND: {sources_ledger_path}", []

    try:
        with open(sources_ledger_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        return False, f"LEDGER_PARSE_ERROR: {e}", []

    sources = data.get('sources', [])
    approved_sources = [
        s for s in sources
        if str(s.get('review_decision', '')).upper() == 'APPROVED'
    ]

    if not approved_sources:
        return False, "NO_APPROVED_SOURCES_FOUND: Ledger contains 0 approved sources", []

    os.makedirs(os.path.dirname(os.path.abspath(queue_output_path)), exist_ok=True)

    tasks = []
    for s in approved_sources:
        source_id = s.get('source_id')
        task = {
            'task_id': f"build_{source_id}",
            'source_id': source_id,
            'canonical_url': s.get('canonical_url'),
            'license_id': s.get('license_id'),
            'status': 'QUEUED',
            'target_db': f"{source_id}.db",
        }
        tasks.append(task)

    queue_payload = {
        'version': 1,
        'queued_tasks_count': len(tasks),
        'tasks': tasks,
    }

    with open(queue_output_path, 'w', encoding='utf-8') as f:
        json.dump(queue_payload, f, indent=2, ensure_ascii=False)

    return True, f"AUTOSEED_SUCCESS: Generated {len(tasks)} tasks from approved sources.", tasks

if __name__ == "__main__":
    ledger = sys.argv[1] if len(sys.argv) > 1 else "legal/ledger/sources.json"
    queue_out = sys.argv[2] if len(sys.argv) > 2 else "tools/gha_factory/queue/active_queue.json"
    ok, msg, generated = autoseed_queue(ledger, queue_out)
    print(f"[{'PASS' if ok else 'FAIL'}] {msg}")
    sys.exit(0 if ok else 1)
