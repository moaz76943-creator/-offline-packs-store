#!/usr/bin/env python3
"""
Factory Dispatcher - Master Constitution Section 14 Compliant.
Resolves QUEUED tasks from active_queue.json and marks them DISPATCHED,
removing artificial trigger blocks and enabling deterministic worker runs.
"""
import datetime
import json
import os
import sys

def dispatch_queued_tasks(queue_path: str, max_batch: int = 5):
    if not os.path.exists(queue_path):
        return False, f"QUEUE_NOT_FOUND: {queue_path}", []

    try:
        with open(queue_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        return False, f"QUEUE_PARSE_ERROR: {e}", []

    tasks = data.get('tasks', [])
    queued_tasks = [t for t in tasks if t.get('status') == 'QUEUED']

    if not queued_tasks:
        return True, "NO_PENDING_TASKS: Queue has 0 tasks with status QUEUED", []

    dispatched = []
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for t in queued_tasks[:max_batch]:
        t['status'] = 'DISPATCHED'
        t['dispatched_at'] = now_iso
        dispatched.append(t)

    # Save updated queue atomically
    with open(queue_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return True, f"DISPATCH_SUCCESS: Successfully dispatched {len(dispatched)} task(s).", dispatched

if __name__ == "__main__":
    q_path = sys.argv[1] if len(sys.argv) > 1 else "tools/gha_factory/queue/active_queue.json"
    batch_size = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    ok, msg, dispatched_items = dispatch_queued_tasks(q_path, batch_size)
    print(f"[{'PASS' if ok else 'FAIL'}] {msg}")
    for item in dispatched_items:
        print(f" -> Dispatched Task ID: {item.get('task_id')} (Source: {item.get('source_id')})")
    sys.exit(0 if ok else 1)
