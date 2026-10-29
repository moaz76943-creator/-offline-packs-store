import os
import sqlite3
from typing import Dict, Any, List, Tuple

def reconcile_manifest_entry(pack_file_path: str, manifest_entry: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Reconciles manifest claims against actual SQLite row counts and metadata.
    Flags any count or schema mismatch between the manifest and the database.
    """
    errors = []
    if not os.path.exists(pack_file_path):
        return False, [f"Target pack file not found: {pack_file_path}"]

    try:
        conn = sqlite3.connect(f"file:{pack_file_path}?mode=ro", uri=True)
        cur = conn.cursor()

        # حساب عدد الصفوف الفعلي في جدول المفردات
        cur.execute("SELECT COUNT(*) FROM vocabulary;")
        actual_count = cur.fetchone()[0]

        # فحص تطابق معرف الحزمة
        cur.execute("SELECT value FROM pack_info WHERE key = 'pack_id';")
        res_pack_id = cur.fetchone()
        db_pack_id = res_pack_id[0] if res_pack_id else None

        conn.close()

        claimed_count = manifest_entry.get("entry_count", 0)
        if actual_count != claimed_count:
            errors.append(f"Row count mismatch: manifest claims {claimed_count}, SQLite contains {actual_count}")

        manifest_pack_id = manifest_entry.get("pack_id")
        if db_pack_id and manifest_pack_id and db_pack_id != manifest_pack_id:
            errors.append(f"Pack ID mismatch: manifest claims '{manifest_pack_id}', SQLite contains '{db_pack_id}'")

    except Exception as e:
        errors.append(f"Failed to inspect SQLite pack database: {str(e)}")

    return len(errors) == 0, errors
