"""Bounded-memory JSONL deduplication CLI; never silently discards invalid rows."""
import argparse
import json
import sys
from .dedupe import CorpusDeduplicator


def process_stream(stream, deduplicator):
    line_number = 0
    while True:
        # Bounded even if input has a single unterminated giant line.
        line = stream.readline(deduplicator.max_record_bytes + 1)
        if not line:
            break
        line_number += 1
        if len(line.encode('utf-8')) > deduplicator.max_record_bytes or not line.endswith('\n') and len(line) > deduplicator.max_record_bytes:
            raise ValueError(f'oversized JSONL line {line_number}')
        if not line.strip():
            continue
        try:
            deduplicator.process_record(json.loads(line))
        except (ValueError, UnicodeError) as exc:
            raise ValueError(f'invalid JSONL record on line {line_number}: {exc}') from exc


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', '-i')
    p.add_argument('--canonical', '-c', required=True)
    p.add_argument('--duplicates', '-d', required=True)
    p.add_argument('--review-required', '-r', required=True)
    args = p.parse_args(argv)
    if args.canonical == args.duplicates or args.canonical == args.review_required or args.duplicates == args.review_required:
        p.error('canonical, duplicates, and review-required paths must differ')
    try:
        with CorpusDeduplicator() as dedup:
            if args.input:
                with open(args.input, encoding='utf-8') as inp:
                    process_stream(inp, dedup)
            else:
                process_stream(sys.stdin, dedup)
            with open(args.canonical, 'w', encoding='utf-8') as canonical, \
                 open(args.duplicates, 'w', encoding='utf-8') as duplicates, \
                 open(args.review_required, 'w', encoding='utf-8') as review_req:
                for kind, record in dedup.iter_resolved():
                    if kind == 'canonical':
                        stream = canonical
                    else:
                        if record.get('status') == 'REVIEW_REQUIRED':
                            stream = review_req
                        else:
                            stream = duplicates
                    stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
    except (OSError, ValueError) as exc:
        print(f'INVALID: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
