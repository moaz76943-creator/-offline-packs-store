"""Rotate enabled languages. Priority orders the ring; it does not drop languages."""

from datetime import date


def enabled_languages(catalog):
    rows = [row for row in catalog.get('languages') or [] if isinstance(row, dict) and row.get('enabled', True)]
    return sorted(rows, key=lambda row: (int(row.get('priority') or 10**6), row.get('id') or ''))


def select_batch(catalog, slot, batch_size=None):
    """Return the languages for this rotation slot. The ring wraps."""
    rows = enabled_languages(catalog)
    if not rows:
        return []
    size = int(batch_size if batch_size is not None else catalog.get('batch_size') or 1)
    if size < 1:
        size = 1
    size = min(size, len(rows))
    start = int(slot) % len(rows)
    ring = rows + rows
    return ring[start:start + size]


def select_coverage_batch(catalog, slot, coverage=None, batch_size=None):
    """Rotate a ring ordered by open concept gaps, largest gap first."""
    rows = enabled_languages(catalog)
    gaps = {}
    if isinstance(coverage, dict):
        for row in coverage.get('languages') or []:
            if isinstance(row, dict) and row.get('id') is not None and row.get('gap_count') is not None:
                gaps[row['id']] = int(row['gap_count'])

    def sort_key(row):
        gap = gaps.get(row['id'], 10**12)
        return (-gap, int(row.get('priority') or 10**6), row.get('id') or '')

    ranked = sorted(rows, key=sort_key)
    if not ranked:
        return []
    size = int(batch_size if batch_size is not None else catalog.get('batch_size') or 1)
    if size < 1:
        size = 1
    size = min(size, len(ranked))
    start = int(slot) % len(ranked)
    ring = ranked + ranked
    return ring[start:start + size]


def rotation_slot(catalog, slot_text='', today=None):
    """Use an explicit slot, otherwise the UTC day-of-year, wrapped over the ring."""
    rows = enabled_languages(catalog)
    if not rows:
        return 0
    text = str(slot_text or '').strip()
    if text:
        return int(text) % len(rows)
    today = today or date.today()
    return today.timetuple().tm_yday % len(rows)
