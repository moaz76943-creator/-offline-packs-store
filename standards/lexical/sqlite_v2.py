#!/usr/bin/env python3
"""Deterministic, non-lossy SQLite v2 projection of validated lexical records.

This is an additive public reference mapper, not a replacement for the existing
store pack compiler. Does not migrate missing-provenance legacy packs.
"""
import argparse
import json
import sqlite3
import sys
import unicodedata
from pathlib import Path

if __package__:
    from .validate import LexicalContractError, validate
else:
    from validate import LexicalContractError, validate

SQLITE_USER_VERSION = 2
MAPPING_VERSION = '2.0.0'
DDL = '''
PRAGMA foreign_keys=ON;
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE schema_migrations(version TEXT PRIMARY KEY, description TEXT NOT NULL);
CREATE TABLE concepts(concept_id TEXT PRIMARY KEY);
CREATE TABLE lexicon(
 id TEXT PRIMARY KEY, surface TEXT NOT NULL, part_of_speech TEXT NOT NULL,
 pos TEXT NOT NULL, direction TEXT NOT NULL, language_code TEXT NOT NULL,
 script TEXT NOT NULL, dialect TEXT, sort_key TEXT NOT NULL,
 cefr_level TEXT, frequency_rank INTEGER, fields_json TEXT NOT NULL,
 source_json TEXT NOT NULL
);
CREATE INDEX idx_lexicon_order ON lexicon(language_code,sort_key,id);
CREATE INDEX idx_lexicon_surface ON lexicon(language_code,surface);
CREATE TABLE senses(
 sense_id TEXT PRIMARY KEY, lexeme_id TEXT NOT NULL REFERENCES lexicon(id),
 concept_id TEXT NOT NULL REFERENCES concepts(concept_id), definition TEXT NOT NULL,
 payload_json TEXT NOT NULL
);
CREATE INDEX idx_senses_lexeme ON senses(lexeme_id,sense_id);
CREATE TABLE translations(
 translation_id TEXT PRIMARY KEY, from_sense_id TEXT NOT NULL REFERENCES senses(sense_id),
 to_sense_id TEXT NOT NULL REFERENCES senses(sense_id), language_code TEXT NOT NULL,
 text TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE INDEX idx_translations_directed ON translations(from_sense_id,language_code,translation_id);
CREATE TABLE examples(
 example_id TEXT PRIMARY KEY, sense_id TEXT NOT NULL REFERENCES senses(sense_id),
 lexeme_id TEXT NOT NULL REFERENCES lexicon(id), language_code TEXT NOT NULL,
 text TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE INDEX idx_examples_sense ON examples(sense_id,example_id);
CREATE TABLE lexical_relations(
 relation_id TEXT PRIMARY KEY, from_lexeme_id TEXT NOT NULL REFERENCES lexicon(id),
 to_lexeme_id TEXT NOT NULL REFERENCES lexicon(id), kind TEXT NOT NULL,
 payload_json TEXT NOT NULL
);
CREATE VIRTUAL TABLE lexicon_fts USING fts5(surface,lemma,gloss,language_code UNINDEXED,
 tokenize='unicode61 remove_diacritics 0');
CREATE VIEW lexemes AS SELECT id,surface,part_of_speech,direction,fields_json FROM lexicon;
'''


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sort_key(value):
    return unicodedata.normalize('NFKC', value).casefold()


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
        conn.execute('INSERT INTO schema_migrations VALUES (?,?)', (MAPPING_VERSION, 'initial public v2 mapping'))
        lexemes = {row['lexeme_id']: row for row in document['lexemes']}
        senses = {row['sense_id']: row for row in document['senses']}
        for cid in sorted({row['concept_id'] for row in senses.values()}):
            conn.execute('INSERT INTO concepts VALUES (?)', (cid,))
        outbound = {}
        for t in document['translations']:
            outbound.setdefault(senses[t['from_sense_id']]['lexeme_id'], []).append(t['text'])
        definitions = {}
        for s in senses.values():
            definitions.setdefault(s['lexeme_id'], []).append(s['definition'])
        for rid in sorted(lexemes, key=lambda key: (lexemes[key]['language'], sort_key(lexemes[key]['surface']), key)):
            row = lexemes[rid]
            levels = [level['level_id'] for sense in senses.values() if sense['lexeme_id'] == rid
                      for level in sense.get('levels', []) if level['framework_id'] == 'cefr']
            cefr = levels[0] if len(set(levels)) == 1 and levels else None
            rank = None  # Ordinal rank is NOT inferred from frequency scores.
            direction = row['direction']  # Explicitly attested; never guess script layout.
            conn.execute('''INSERT INTO lexicon
                (id,surface,part_of_speech,pos,direction,language_code,script,dialect,
                 sort_key,cefr_level,frequency_rank,fields_json,source_json)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (rid,row['surface'],row['pos'],row['pos'],direction,row['language'],row['script'],
                 row.get('dialect'),sort_key(row['surface']),cefr,rank,compact(row),compact(row['source'])))
            rowid = conn.execute('SELECT rowid FROM lexicon WHERE id=?',(rid,)).fetchone()[0]
            gloss = ' '.join(sorted(set(definitions.get(rid, []) + outbound.get(rid, []))))
            conn.execute('INSERT INTO lexicon_fts(rowid,surface,lemma,gloss,language_code) VALUES (?,?,?,?,?)',
                         (rowid,row['surface'],row['lemma'],gloss,row['language']))
        for sid in sorted(senses):
            row = senses[sid]
            conn.execute('INSERT INTO senses VALUES (?,?,?,?,?)',
                         (sid,row['lexeme_id'],row['concept_id'],row['definition'],compact(row)))
        for row in sorted(document['translations'], key=lambda r:r['translation_id']):
            conn.execute('INSERT INTO translations VALUES (?,?,?,?,?,?)',
                         (row['translation_id'],row['from_sense_id'],row['to_sense_id'],
                          row['language'],row['text'],compact(row)))
        for row in sorted(document['examples'],key=lambda r:r['example_id']):
            conn.execute('INSERT INTO examples VALUES (?,?,?,?,?,?)',
                         (row['example_id'],row['sense_id'],senses[row['sense_id']]['lexeme_id'],
                          row['language'],row['text'],compact(row)))
        for row in sorted(document['relations'],key=lambda r:r['relation_id']):
            conn.execute('INSERT INTO lexical_relations VALUES (?,?,?,?,?)',
                         (row['relation_id'],row['from_lexeme_id'],row['to_lexeme_id'],
                          row['kind'],compact(row)))
        conn.execute("INSERT INTO lexicon_fts(lexicon_fts) VALUES('integrity-check')")
        conn.execute(f'PRAGMA user_version={SQLITE_USER_VERSION}')
        conn.commit()
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise LexicalContractError('SQLite integrity check failed')
        if conn.execute('PRAGMA foreign_key_check').fetchall():
            raise LexicalContractError('SQLite foreign-key check failed')
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
        raise LexicalContractError(f'no safe migration from SQLite user_version {version}')
    metadata = dict(conn.execute('SELECT key,value FROM metadata'))
    if metadata.get('mapping_version') != MAPPING_VERSION or metadata.get('contract_version') != '1.0.0':
        raise LexicalContractError('unrecognized mapping or contract version; explicit migration required')
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
