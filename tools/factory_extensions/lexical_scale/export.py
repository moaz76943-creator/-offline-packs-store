"""Stream bounded, non-publishable Route06 lexical fragments from an admitted shard."""
import argparse
import hashlib
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from tools.factory_extensions.lexical_scale.adapter import canonical


def export_fragments(checkpoint, language, out, *, max_lexemes=200):
    if type(max_lexemes) is not int or not 1 <= max_lexemes <= 1000:
        raise ValueError('INVALID_DOCUMENT_LIMIT')
    out = Path(out)
    if out.exists() or out.is_symlink() or not out.parent.is_dir():
        raise ValueError('OUTPUT_EXISTS_OR_PARENT_MISSING')
    stage = Path(tempfile.mkdtemp(prefix='.lexical-scale-', dir=out.parent))
    try:
        with sqlite3.connect(f'file:{Path(checkpoint).resolve()}?mode=ro', uri=True) as db:
            state = db.execute('SELECT identity, counters FROM state WHERE id=1').fetchone()
            if not state:
                raise ValueError('NO_CHECKPOINT')
            docs = []
            count = 0
            batch = []

            def flush():
                nonlocal batch
                if not batch:
                    return
                index = len(docs)
                doc = {'contract_version': '1.0.0', 'document_id': f'scale.{language}.{index:08d}',
                       'lexemes': [x[0] for x in batch],
                       'senses': [sense for _, senses in batch for sense in senses],
                       'translations': [], 'examples': [], 'relations': []}
                raw = (canonical(doc) + '\n').encode('utf-8')
                name = f'fragment-{index:08d}.json'
                (stage / name).write_bytes(raw)
                docs.append({'path': name, 'sha256': hashlib.sha256(raw).hexdigest(),
                             'lexemes': len(doc['lexemes']), 'senses': len(doc['senses'])})
                batch = []

            for (raw,) in db.execute('SELECT payload FROM lexemes ORDER BY id'):
                entry = json.loads(raw)
                if entry.get('language') != language or entry['source'].get('publication_approved') is not False:
                    raise ValueError('INCONSISTENT_SHARD_IDENTITY_OR_PUBLICATION')
                senses = [json.loads(rec[0]) for rec in db.execute(
                    'SELECT payload FROM senses WHERE lexeme=? ORDER BY id', (entry['lexeme_id'],))]
                if not senses:
                    raise ValueError('ORPHAN_LEXEME')
                batch.append((entry, senses))
                count += 1
                if len(batch) >= max_lexemes:
                    flush()
            flush()
            manifest = {'status': 'REVIEW_REQUIRED', 'contract_version': '1.0.0',
                        'checkpoint_id': state[0], 'language': language,
                        'publication_approved': False, 'accepted_lexemes': count,
                        'accepted_senses': sum(x['senses'] for x in docs), 'fragments': docs}
            (stage / 'manifest.json').write_text(canonical(manifest) + '\n', encoding='utf-8')
        if out.exists() or out.is_symlink():
            raise ValueError('OUTPUT_CONCURRENTLY_CREATED')
        stage.rename(out)
        return manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkpoint', type=Path, required=True)
    p.add_argument('--language', required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--max-lexemes', type=int, default=200)
    a = p.parse_args(argv)
    print(canonical(export_fragments(a.checkpoint, a.language, a.out, max_lexemes=a.max_lexemes)))


if __name__ == '__main__':
    main()
