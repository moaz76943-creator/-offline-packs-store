"""Write one language overlay. Shared concept ids are the join key; pair databases are not created."""

import json
import sqlite3
from pathlib import Path

LEXICAL_DIR_NAME = 'standards/lexical'


def source_record(language_id, dataset_version, origin_url, locator):
    return {
        'source_id': 'wikidata.lexemes',
        'origin_url': origin_url,
        'publisher': 'Wikimedia Foundation',
        'dataset_version': dataset_version,
        'retrieval_id': f'wikidata-{dataset_version}-lexemes.json.gz',
        'license_id': 'CC0-1.0',
        'record_locator': locator,
        'artifact_sha256': None,
        'publication_approved': False,
        'fixture_only': False,
    }


def to_document(language_id, records, dataset_version, origin_url):
    """Build a lexical contract document. examples stay empty until a sentence source is approved."""
    lexemes = []
    senses = []
    for record in records:
        lexemes.append(record['lexeme'])
        senses.extend(record['senses'])
    return {
        'contract_version': '1.0.0',
        'document_id': f'candidate.wikidata.{language_id}.{dataset_version}',
        'lexemes': lexemes,
        'senses': senses,
        'translations': [],
        'examples': [],
        'relations': [],
    }


def concept_index(records):
    concepts = sorted({sense['concept_id'] for record in records for sense in record['senses']})
    return {
        'schema_version': '1.0.0',
        'join': 'shared concept_id; directed pairs are derived at runtime from per-language overlays',
        'pair_databases': 0,
        'concepts': concepts,
    }


def write_overlay(language_id, records, output, dataset_version, origin_url):
    document = to_document(language_id, records, dataset_version, origin_url)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    lexical_dir = Path(__file__).resolve().parents[2] / LEXICAL_DIR_NAME
    import sys
    if str(lexical_dir) not in sys.path:
        sys.path.insert(0, str(lexical_dir))
    from sqlite_v2 import build
    build(document, output, publication=False)
    _add_grammar(output, language_id, records)
    index_path = output.with_suffix('.concepts.json')
    index_path.write_text(json.dumps(concept_index(records), indent=2) + '\n', encoding='utf-8')
    return document


def _add_grammar(output, language_id, records):
    connection = sqlite3.connect(output)
    try:
        connection.execute('''CREATE TABLE IF NOT EXISTS grammar (
            grammar_id TEXT PRIMARY KEY,
            language_code TEXT NOT NULL,
            topic TEXT NOT NULL,
            level_id TEXT,
            level_assignment TEXT NOT NULL CHECK (level_assignment = 'estimated'),
            payload_json TEXT NOT NULL
        )''')
        connection.execute(
            'INSERT OR IGNORE INTO schema_migrations VALUES (?, ?)',
            ('production-grammar-1', 'estimated grammar rows for attested forms'),
        )
        for record in records:
            grammar = record.get('grammar')
            if not grammar:
                continue
            connection.execute(
                'INSERT INTO grammar VALUES (?, ?, ?, ?, ?, ?)',
                (
                    grammar['grammar_id'],
                    language_id,
                    grammar['topic'],
                    grammar['level_id'],
                    'estimated',
                    json.dumps(grammar['payload'], ensure_ascii=False, sort_keys=True),
                ),
            )
        connection.commit()
    finally:
        connection.close()
