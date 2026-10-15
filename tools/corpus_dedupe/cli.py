import argparse
import sys
import json
from pathlib import Path
from typing import List, Optional
from .engine import CorpusDeduplicator

def run(args: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(description='Bounded streaming corpus deduplicator.')
    parser.add_argument('inputs', nargs='*', type=Path, help='Input JSONL files.')
    parser.add_argument('--out-dir', type=Path, required=True, help='Output directory for canonical, duplicates, and review_required JSONL files.')

    parsed = parser.parse_args(args)

    parsed.out_dir.mkdir(parents=True, exist_ok=True)

    canonical_file = parsed.out_dir / 'canonical.jsonl'
    duplicates_file = parsed.out_dir / 'duplicates.jsonl'
    review_file = parsed.out_dir / 'review_required.jsonl'

    deduper = CorpusDeduplicator()

    if not parsed.inputs:
        for line in sys.stdin:
            if line.strip():
                deduper.add_record(json.loads(line))
    else:
        for filepath in parsed.inputs:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        deduper.add_record(json.loads(line))

    with open(canonical_file, 'w', encoding='utf-8') as f_can, \
         open(duplicates_file, 'w', encoding='utf-8') as f_dup, \
         open(review_file, 'w', encoding='utf-8') as f_rev:

        for c_rec, dups, revs in deduper.process():
            f_can.write(json.dumps(c_rec) + '\n')

            for d in dups:
                f_dup.write(json.dumps({
                    'canonical_id': c_rec.get('lexeme_id'),
                    'duplicate_id': d.get('lexeme_id'),
                    'record': d
                }) + '\n')

            for r in revs:
                f_rev.write(json.dumps({
                    'canonical_id': c_rec.get('lexeme_id'),
                    'review_id': r.get('lexeme_id'),
                    'record': r
                }) + '\n')

    deduper.close()

if __name__ == '__main__':
    run()
