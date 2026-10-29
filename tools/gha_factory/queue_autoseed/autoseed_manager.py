import json
import os
from typing import Dict, Any, List

def generate_queue_tasks(sources_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Reads approved sources and deterministically generates pending build tasks
    into active_queue.json format.
    """
    tasks = []
    sources = sources_data.get("approved_sources", [])

    for src in sources:
        if src.get("legal_review_status") != "APPROVED":
            continue

        source_id = src.get("source_id", "")
        # استنتاج الزوج اللغوي والمهمة بناءً على source_id
        if "de" in source_id:
            tasks.append({
                "task_id": f"build_{source_id}_a1",
                "source_id": source_id,
                "source_lang": "de",
                "target_lang": "ar",
                "cefr_level": "A1",
                "status": "PENDING",
                "source_sha256": src.get("sha256", ""),
            })

    return tasks

def sync_active_queue(sources_path: str, queue_path: str) -> int:
    if not os.path.exists(sources_path):
        return 0

    with open(sources_path, "r", encoding="utf-8") as f:
        sources_data = json.load(f)

    new_tasks = generate_queue_tasks(sources_data)
    
    os.makedirs(os.path.dirname(queue_path), exist_ok=True)
    with open(queue_path, "w", encoding="utf-8") as f:
        json.dump({"tasks": new_tasks}, f, indent=2)

    return len(new_tasks)
