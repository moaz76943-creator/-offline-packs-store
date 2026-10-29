#!/usr/bin/env python3
"""Language-production commands used by the scheduled workflow and by tests."""

import argparse
import json
import sys
from pathlib import Path

from tools.language_production.catalog import load_languages, load_sections
from tools.language_production.checkpoint import advance_cursor, byte_range, load_cursor
from tools.language_production.dumps import resolve_dump_date
from tools.language_production.harvest import HarvestConfig, harvest_dump
from tools.language_production.publish import merge_decision
from tools.language_production.repair import note_failure, note_success, should_advance, slice_budget
from tools.language_production.schedule import rotation_slot, select_coverage_batch
from tools.language_production.source_gate import missing_issue_titles
from tools.language_production.status_report import combine_reports, render_status

MIN_BYTES = 1048576
MAX_BYTES = 8388608
MIN_LEXEMES = 1
MAX_LEXEMES = 200


def _load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _check_bounds(max_bytes, max_lexemes):
    if not MIN_BYTES <= int(max_bytes) <= MAX_BYTES:
        raise ValueError(f'max_bytes must be {MIN_BYTES}..{MAX_BYTES}')
    if not MIN_LEXEMES <= int(max_lexemes) <= MAX_LEXEMES:
        raise ValueError(f'max_lexemes must be {MIN_LEXEMES}..{MAX_LEXEMES}')


def command_plan(args):
    catalog = load_languages()
    _check_bounds(args.max_bytes, args.max_lexemes)
    slot = rotation_slot(catalog, args.slot)
    coverage = None
    coverage_path = args.coverage or 'dist/state/language-production/coverage.json'
    if Path(coverage_path).is_file():
        coverage = _load_json(coverage_path)
    batch = select_coverage_batch(catalog, slot, coverage)
    matrix = {'language': [row['id'] for row in batch]}
    state = {}
    if args.repair_state and Path(args.repair_state).is_file():
        state = _load_json(args.repair_state)
    budget = slice_budget(args.max_bytes, state)
    cursor = load_cursor(args.cursor) if args.cursor else {'next_offset': 0, 'dump_date': ''}
    start, last = byte_range(cursor['next_offset'], budget)
    print(f'matrix={json.dumps(matrix, separators=(",", ":"))}')
    print(f'slot={slot}')
    print(f'dump_date={args.dump_date}')
    print(f'max_bytes={budget}')
    print(f'max_lexemes={int(args.max_lexemes)}')
    print(f'range_start={start}')
    print(f'range_end={last}')
    return 0


def command_harvest(args):
    _check_bounds(args.max_bytes, args.max_lexemes)
    catalog = load_languages()
    rows = [row for row in catalog['languages'] if row['id'] == args.language]
    if not rows:
        raise ValueError(f'unknown production language {args.language}')
    config = HarvestConfig(
        dataset_version=args.dataset_version,
        origin_url=args.origin_url,
        max_lexemes=int(args.max_lexemes),
        output=args.output,
    )
    summary = harvest_dump(
        args.dump,
        rows[0],
        config,
        taxonomy=load_sections(),
    )
    Path(args.summary).parent.mkdir(parents=True, exist_ok=True)
    Path(args.summary).write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, sort_keys=True))
    return 0


def command_status(args):
    reports = [_load_json(path) for path in args.reports]
    report = combine_reports(
        reports,
        dump_date=args.dump_date,
        batch_slot=None if args.slot == '' else int(args.slot),
        slice_bytes=None if args.slice_bytes == '' else int(args.slice_bytes),
    )
    text = render_status(report)
    Path(args.output).write_text(text, encoding='utf-8')
    return 0


def command_repair(args):
    path = Path(args.state)
    state = _load_json(path) if path.is_file() else {}
    if args.success:
        state = note_success(state)
        plan = {'action': 'ok', 'attempts': 0, 'signature': ''}
    else:
        state, plan = note_failure(state, args.signature)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
    advance = should_advance(args.success, plan)
    print(json.dumps({'plan': plan, 'advance': advance}, sort_keys=True))
    return 0


def command_advance(args):
    payload = advance_cursor(
        args.cursor,
        dump_date=args.dump_date,
        downloaded_bytes=int(args.downloaded_bytes),
        wrapped=args.wrapped,
    )
    print(json.dumps(payload, sort_keys=True))
    return 0


def command_missing_issues(args):
    existing = []
    if args.titles:
        existing = _load_json(args.titles)
    missing = missing_issue_titles(existing if isinstance(existing, list) else [])
    print(json.dumps(missing))
    return 0


def command_merge_decision(args):
    checks = _load_json(args.checks)
    decision, reason = merge_decision(checks, int(args.unresolved_threads), halt=args.halt)
    print(json.dumps({'merge': decision, 'reason': reason}, sort_keys=True))
    return 0 if decision or args.allow_skip else 1


def command_latest_dump_date(args):
    html = sys.stdin.read() if args.html == '-' else Path(args.html).read_text(encoding='utf-8')
    print(resolve_dump_date(args.preferred, html))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)

    plan = commands.add_parser('plan')
    plan.add_argument('--slot', default='')
    plan.add_argument('--dump-date', required=True)
    plan.add_argument('--max-bytes', type=int, required=True)
    plan.add_argument('--max-lexemes', type=int, required=True)
    plan.add_argument('--cursor', default='')
    plan.add_argument('--repair-state', default='')
    plan.add_argument('--coverage', default='')
    plan.set_defaults(func=command_plan)

    harvest = commands.add_parser('harvest')
    harvest.add_argument('--dump', required=True)
    harvest.add_argument('--language', required=True)
    harvest.add_argument('--output', required=True)
    harvest.add_argument('--summary', required=True)
    harvest.add_argument('--dataset-version', required=True)
    harvest.add_argument('--origin-url', required=True)
    harvest.add_argument('--max-bytes', type=int, required=True)
    harvest.add_argument('--max-lexemes', type=int, required=True)
    harvest.set_defaults(func=command_harvest)

    status = commands.add_parser('status')
    status.add_argument('--reports', nargs='+', required=True)
    status.add_argument('--output', required=True)
    status.add_argument('--dump-date', default='')
    status.add_argument('--slot', default='')
    status.add_argument('--slice-bytes', default='')
    status.set_defaults(func=command_status)

    repair = commands.add_parser('repair')
    repair.add_argument('--state', required=True)
    repair.add_argument('--signature', default='')
    repair.add_argument('--success', action='store_true')
    repair.set_defaults(func=command_repair)

    advance = commands.add_parser('advance')
    advance.add_argument('--cursor', required=True)
    advance.add_argument('--dump-date', required=True)
    advance.add_argument('--downloaded-bytes', required=True)
    advance.add_argument('--wrapped', action='store_true')
    advance.set_defaults(func=command_advance)

    issues = commands.add_parser('missing-issues')
    issues.add_argument('--titles', default='')
    issues.set_defaults(func=command_missing_issues)

    merge = commands.add_parser('merge-decision')
    merge.add_argument('--checks', required=True)
    merge.add_argument('--unresolved-threads', type=int, default=0)
    merge.add_argument('--halt', action='store_true')
    merge.add_argument('--allow-skip', action='store_true')
    merge.set_defaults(func=command_merge_decision)

    latest = commands.add_parser('latest-dump-date')
    latest.add_argument('--html', required=True)
    latest.add_argument('--preferred', default='')
    latest.set_defaults(func=command_latest_dump_date)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
