import json
import os
from typing import Union, List, Dict, Any

class ZeroYieldError(Exception):
    """Raised when an ETL pipeline or worker produces zero yield/records."""
    pass

def verify_non_zero_yield(data_or_path: Union[str, List[Any], Dict[Any, Any]], min_threshold: int = 1) -> int:
    """
    Enforces fail-closed validation on worker outputs.
    Raises ZeroYieldError if the artifact is missing, 0-byte, or empty.
    """
    if isinstance(data_or_path, str):
        if not os.path.exists(data_or_path):
            raise ZeroYieldError(f"Artifact file does not exist: {data_or_path}")
        if os.path.getsize(data_or_path) == 0:
            raise ZeroYieldError(f"Artifact file is empty (0 bytes): {data_or_path}")

        try:
            with open(data_or_path, "r", encoding="utf-8") as f:
                parsed = json.load(f)
            return verify_non_zero_yield(parsed, min_threshold)
        except json.JSONDecodeError as e:
            raise ZeroYieldError(f"Corrupted or invalid JSON artifact: {str(e)}")

    if isinstance(data_or_path, (list, dict)):
        count = len(data_or_path)
        if count < min_threshold:
            raise ZeroYieldError(f"Yield count ({count}) is below minimum threshold ({min_threshold})")
        return count

    raise ZeroYieldError(f"Unsupported payload type for zero-yield validation: {type(data_or_path)}")
