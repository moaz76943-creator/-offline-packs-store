from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

def dispatch_next_task(tasks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Selects the next PENDING task, marks it IN_PROGRESS with UTC timestamp,
    and prevents duplicate in-flight dispatches.
    """
    for task in tasks:
        if task.get("status") == "PENDING":
            task["status"] = "IN_PROGRESS"
            task["dispatched_at"] = datetime.now(timezone.utc).isoformat()
            return task
    return None

def complete_task(tasks: List[Dict[str, Any]], task_id: str, success: bool) -> bool:
    for task in tasks:
        if task.get("task_id") == task_id:
            task["status"] = "COMPLETED" if success else "FAILED"
            task["completed_at"] = datetime.now(timezone.utc).isoformat()
            return True
    return False
