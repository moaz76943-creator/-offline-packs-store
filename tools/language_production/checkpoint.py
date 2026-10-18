"""Byte cursor for the next bounded dump slice. A missing file starts at offset 0."""

import json
from pathlib import Path


def load_cursor(path):
    file = Path(path)
    if not file.is_file():
        return {'next_offset': 0, 'dump_date': ''}
    data = json.loads(file.read_text(encoding='utf-8'))
    offset = data.get('next_offset') if isinstance(data, dict) else 0
    if not isinstance(offset, int) or offset < 0:
        offset = 0
    date = data.get('dump_date') if isinstance(data, dict) else ''
    if not isinstance(date, str):
        date = ''
    return {'next_offset': offset, 'dump_date': date}


def advance_cursor(path, *, dump_date, downloaded_bytes, wrapped=False):
    current = load_cursor(path)
    if wrapped or current.get('dump_date') not in ('', dump_date):
        offset = 0
    else:
        offset = current['next_offset']
    offset += max(0, int(downloaded_bytes))
    payload = {'next_offset': offset, 'dump_date': dump_date}
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    return payload


def byte_range(offset, max_bytes):
    """Inclusive HTTP range for one bounded slice."""
    start = max(0, int(offset))
    last = start + max(1, int(max_bytes)) - 1
    return start, last
