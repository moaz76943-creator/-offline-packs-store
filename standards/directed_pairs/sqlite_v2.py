#!/usr/bin/env python3
"""Deterministic, non-lossy SQLite v2 projection of validated directed pairs.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

from validate import DirectedPairContractError, validate

SQLITE_USER_VERSION = 2
MAPPING_VERSION = '2.0.0'
DDL = '''
PRAGMA foreign_keys=ON;
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE schema_migrations(version TEXT PRIMARY KEY, description TEXT NOT NULL);
CREATE TABLE concepts(concept_id TEXT PRIMARY KEY);
CREATE TABLE senses(
 sense_id TEXT PRIMARY KEY, lexeme_id TEXT NOT NULL,
 concept_id TEXT NOT NULL REFERENCES concepts(concept_id), definition TEXT NOT NULL,
 payload_json TEXT NOT NULL
);
CREATE INDEX idx_senses_lexeme ON senses(lexeme_id,sense_id);
CREATE TABLE directed_pairs(
 pair_id TEXT PRIMARY KEY, source_sense_id TEXT NOT NULL REFERENCES senses(sense_id),
 target_sense_id TEXT NOT NULL REFERENCES senses(sense_id), source_language TEXT NOT NULL,
 target_language TEXT NOT NULL, text TEXT NOT NULL, equivalence TEXT NOT NULL,
 payload_json TEXT NOT NULL
);
CREATE INDEX idx_directed_pairs_directed ON directed_pairs(source_sense_id,target_language,pair_id);
'''


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def build(document, output, *, publication=False):
    """Validate before touching output; output must be new, never overwrite user DB."""
    validate(document, publication=publication)
    output = Path(output)
    if output.exists():
        raise FileExistsError(f'refusing to overwrite {output}')
    if not output.parent.is_dir():
        raise FileNotFoundError(f'output parent does not exist: {output.parent}')
    conn = sqlite3.connect(output)
    try:
        conn.executescript(DDL)
        conn.execute('INSERT INTO metadata VALUES (?,?)', ('contract_version', document['contract_version']))
        conn.execute('INSERT INTO metadata VALUES (?,?)', ('mapping_version', MAPPING_VERSION))
        conn.execute('INSERT INTO metadata VALUES (?,?)', ('document_id', document['document_id']))
        conn.execute('INSERT INTO schema_migrations VALUES (?,?)', (MAPPING_VERSION, 'initial public directed pair mapping'))
        senses = {row['sense_id']: row for row in document['senses']}
        for cid in sorted({row['concept_id'] for row in senses.values()}):
            conn.execute('INSERT INTO concepts VALUES (?)', (cid,))

        for sid in sorted(senses):
            row = senses[sid]
            conn.execute('INSERT INTO senses VALUES (?,?,?,?,?)',
                         (sid,row['lexeme_id'],row['concept_id'],row['definition'],compact(row)))
        for row in sorted(document['directed_translations'], key=lambda r:r['pair_id']):
            conn.execute('INSERT INTO directed_pairs VALUES (?,?,?,?,?,?,?,?)',
                         (row['pair_id'],row['source_sense_id'],row['target_sense_id'],
                          row['source_language'],row['target_language'],row['text'],row['equivalence'],compact(row)))
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


def check_mapping_version(conn):
    version = conn.execute('PRAGMA user_version').fetchone()[0]
    if version != SQLITE_USER_VERSION:
        raise DirectedPairContractError(f'no safe migration from SQLite user_version {version}')
    metadata = dict(conn.execute('SELECT key,value FROM metadata'))
    if metadata.get('mapping_version') != MAPPING_VERSION or metadata.get('contract_version') != '1.0.0':
        raise DirectedPairContractError('unrecognized mapping or contract version; explicit migration required')
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--publication', action='store_true')
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.input.read_text(encoding='utf-8'))
        build(document,args.output,publication=args.publication)
    except (OSError, ValueError,sqlite3.Error) as exc:
        print(f'INVALID: {exc}',file=sys.stderr)
        return 1
    print('OK: SQLite v2 projection created')
    return 0


if __name__ == '__main__':
    sys.exit(main())
