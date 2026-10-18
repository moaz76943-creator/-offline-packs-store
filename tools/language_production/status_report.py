"""Render STATUS.md from a harvest report. Counts come only from that report."""


def render_status(report):
    report = report or {}
    languages = report.get('languages') or []
    lines = [
        '# Language production status',
        '',
        'Scheduled production is language-generic. Each run takes one bounded slice of the',
        'Wikidata lexeme dump and writes per-language overlays that share concept ids.',
        'Directed translation pairs are not stored. Sentences stay empty until the owner',
        'approves a compatible sentence source.',
        '',
        f"Dump date: {report.get('dump_date') or 'none yet'}",
        f"Batch slot: {report.get('batch_slot') if report.get('batch_slot') is not None else 'n/a'}",
        f"Slice bytes: {report.get('slice_bytes') if report.get('slice_bytes') is not None else 'n/a'}",
        f"Checksum verified: {str(bool(report.get('checksum_verified'))).lower()}",
        f"Quarantined records: {report.get('quarantined') or 0}",
        f"Excluded by content policy: {report.get('excluded') or 0}",
        '',
        '| Language | Lexemes | Sections | Estimated levels | Quarantined |',
        '| --- | ---: | --- | --- | ---: |',
    ]
    if not languages:
        lines.append('| — | 0 | — | — | 0 |')
    for row in languages:
        sections = ', '.join(row.get('sections') or []) or '—'
        levels = ', '.join(row.get('levels') or []) or '—'
        lines.append(
            f"| {row.get('id')} | {row.get('lexemes') or 0} | {sections} | {levels} | {row.get('quarantined') or 0} |"
        )
    coverage = report.get('coverage') or []
    if coverage:
        lines.extend([
            '',
            '| Language | Concept fill | Open gaps |',
            '| --- | ---: | ---: |',
        ])
        for row in coverage:
            lines.append(
                f"| {row.get('id')} | {row.get('fill_ratio')} | {row.get('gap_count')} |"
            )
    lines.extend([
        '',
        'Level labels are `estimated:heuristic-v1`, not corpus bands.',
        'Kill switch: set repository variable `LANGUAGE_PRODUCTION_HALT` to `true` to stop scheduled runs.',
        'Sentence source: issue titled `Source decision: Tatoeba`. Only `moaz76943-creator` can approve it with a line `decision: approve`.',
        '',
    ])
    return '\n'.join(lines)


def combine_reports(reports, *, dump_date, batch_slot, slice_bytes):
    """One STATUS report from per-language harvest summaries. A range slice is never checksum-verified."""
    languages = [row for row in reports or [] if isinstance(row, dict)]
    return {
        'dump_date': dump_date,
        'batch_slot': batch_slot,
        'slice_bytes': slice_bytes,
        'checksum_verified': False,
        'quarantined': sum(int(row.get('quarantined') or 0) for row in languages),
        'excluded': sum(int(row.get('excluded') or 0) for row in languages),
        'languages': languages,
    }
