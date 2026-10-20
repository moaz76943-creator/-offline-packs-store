"""Locate a published Wikidata lexeme dump date. Does not download the dump."""

import re

DATE_LINK = re.compile(r'href="(\d{8})/"')
DATE = re.compile(r'^[0-9]{8}$')


def latest_dump_date(index_html):
    """Return the newest YYYYMMDD directory linked from the entities index."""
    dates = DATE_LINK.findall(index_html or '')
    if not dates:
        raise ValueError('wikidata entities index has no dated dump directory')
    return max(dates)


def resolve_dump_date(preferred, index_html=None):
    """Use an explicit YYYYMMDD, otherwise the newest date in the index HTML."""
    text = str(preferred or '').strip()
    if DATE.fullmatch(text):
        return text
    if index_html is None:
        raise ValueError('dump date must be YYYYMMDD')
    return latest_dump_date(index_html)
