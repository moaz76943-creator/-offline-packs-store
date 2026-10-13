"""Truthful 100-language audit: distinguish not processed from measured zero."""
import argparse
import json
from pathlib import Path
from tools.factory_extensions.lexical_scale.adapter import language_registry, quality_flags, canonical


def coverage(root, receipts):
    languages = language_registry(root)
    results = {name: {'status': 'NOT_PROCESSED', 'source_rows': None,
                      'accepted_lexemes': None, 'accepted_senses': None,
                      'rejected_rows': None, 'coverage_gaps': ['NO_VERIFIED_INGESTION_RECEIPT']}
               for name in languages}
    grouped = {}
    keys = set()
    for item in receipts:
        if not isinstance(item, dict) or item.get('language') not in languages or item.get('status') != 'REVIEW_REQUIRED':
            raise ValueError('INVALID_RECEIPT')
        if not item.get('complete') or not item.get('checkpoint_id') or not item.get('source_sha256'):
            raise ValueError('UNVERIFIED_INCOMPLETE_RECEIPT')
        identity = (item['source_id'], item['language'], item['source_sha256'], item['shard'], item['shards'])
        if identity in keys:
            raise ValueError('DUPLICATE_SHARD_RECEIPT')
        keys.add(identity)
        grouped.setdefault(item['language'], []).append(item)
    for lang, entries in grouped.items():
        # Every independent shard scans the complete input; source rows must not be summed.
        by_source = {}
        for x in entries:
            group = by_source.setdefault((x['source_id'], x['source_sha256'], x['shards']), [])
            group.append(x)
        for group in by_source.values():
            if len(group) != group[0]['shards'] or {x['shard'] for x in group} != set(range(group[0]['shards'])):
                raise ValueError('INCOMPLETE_SHARD_SET')
            if len({x['source_rows'] for x in group}) != 1:
                raise ValueError('SHARD_SOURCE_ROW_MISMATCH')
        results[lang] = {'status': 'REVIEW_REQUIRED',
                         'source_rows': sum(x[0]['source_rows'] for x in by_source.values()),
                         'accepted_lexemes': sum(x['accepted_lexemes'] for x in entries),
                         'accepted_senses': sum(x['accepted_senses'] for x in entries),
                         'rejected_rows': sum(x['rejected_rows'] for x in entries),
                         'coverage_gaps': sorted({g for x in entries for g in x.get('coverage_gaps', [])})}
    measured = {k:v for k,v in results.items() if v['status']=='REVIEW_REQUIRED'}
    return {'status': 'CANDIDATE_RECEIPT_SUMMARY_ONLY', 'registered_languages': len(languages),
            'measured_languages': len(measured), 'quality_flags': quality_flags(measured),
            'languages': results, 'publication_approved': False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path.cwd())
    p.add_argument('receipts', type=Path, nargs='*')
    args=p.parse_args(argv)
    print(canonical(coverage(args.root,[json.loads(x.read_text(encoding='utf-8')) for x in args.receipts])))


if __name__ == '__main__':
    main()
