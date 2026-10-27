#!/usr/bin/env python3
"""Deterministic SQLite v2 projection of validated directed pairs."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

if __package__:
    from .validate import DirectedPairContractError, validate
else:
    from validate import DirectedPairContractError, validate

SQLITE_USER_VERSION = 2
MAPPING_VERSION = '1.0.0'
DDL = '''
PRAGMA foreign_keys=ON;
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE schema_migrations(version TEXT PRIMARY KEY, description TEXT NOT NULL);
CREATE TABLE senses(
 sense_id TEXT PRIMARY KEY, language TEXT NOT NULL, text TEXT NOT NULL,
 context TEXT, domain TEXT, payload_json TEXT NOT NULL
);
CREATE TABLE directed_pairs(
 translation_id TEXT PRIMARY KEY, from_sense_id TEXT NOT NULL REFERENCES senses(sense_id),
 to_sense_id TEXT NOT NULL REFERENCES senses(sense_id), equivalence TEXT NOT NULL,
 payload_json TEXT NOT NULL
);
CREATE INDEX idx_directed_pairs_from ON directed_pairs(from_sense_id);
CREATE INDEX idx_directed_pairs_to ON directed_pairs(to_sense_id);
'''

def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def build(document, output):
    """Validate before touching output; output must be new, never overwrite user DB."""
    validate(document)
    output = Path(output)
    if output.exists():
        raise FileExistsError(f'refusing to overwrite {output}')
    if not output.parent.is_dir():
        raise FileNotFoundError(f'output parent does not exist: {output.parent}')

    conn = sqlite3.connect(output)
    try:
        conn.executescript(DDL)
        conn.execute('INSERT INTO metadata VALUES (?,?)', ('contract_version', '1.0.0'))
        conn.execute('INSERT INTO metadata VALUES (?,?)', ('mapping_version', MAPPING_VERSION))
        conn.execute('INSERT INTO metadata VALUES (?,?)', ('document_id', document['document_id']))
        conn.execute('INSERT INTO schema_migrations VALUES (?,?)', (MAPPING_VERSION, 'initial public v2 mapping'))

        sense_cache = set()

        for pair in sorted(document.get('pairs', []), key=lambda p: p['translation_id']):
            for sense in (pair['from_sense'], pair['to_sense']):
                sid = sense['sense_id']
                if sid not in sense_cache:
                    conn.execute('''
                        INSERT INTO senses (sense_id, language, text, context, domain, payload_json)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (sid, sense['language'], sense['text'], sense.get('context'), sense.get('domain'), compact(sense)))
                    sense_cache.add(sid)

            conn.execute('''
                INSERT INTO directed_pairs (translation_id, from_sense_id, to_sense_id, equivalence, payload_json)
                VALUES (?, ?, ?, ?, ?)
            ''', (pair['translation_id'], pair['from_sense']['sense_id'], pair['to_sense']['sense_id'], pair['equivalence'], compact(pair)))

        conn.execute(f'PRAGMA user_version={SQLITE_USER_VERSION}')
        conn.commit()
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise DirectedPairContractError('SQLite integrity check failed')
        if conn.execute('PRAGMA foreign_key_check').fetchall():
            raise DirectedPairContractError('SQLite foreign-key check failed')
    except BaseException:
        conn.close()
        output.unlink(missing_ok=True)
        raise
    else:
        conn.close()
    return output

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.input.read_text(encoding='utf-8'))
        build(document, args.output)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f'INVALID: {exc}', file=sys.stderr)
        return 1
    print('OK: SQLite v2 projection created')
    return 0

if __name__ == '__main__':
    sys.exit(main())
