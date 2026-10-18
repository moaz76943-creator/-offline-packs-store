"""Fixture-only Wikidata lexeme extract. No network and no ledger edits."""
import gzip
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.wikidata_lexemes.extract_de_verbs import ExtractError, GzipLineReader, extract, gunzip_bytes

ROOT = Path(__file__).resolve().parents[2]
BLOCKLIST = Path(__file__).with_name('blocklist.json')
DATE = '20260101'
DUMP_NAME = f'wikidata-{DATE}-lexemes.json.gz'
ORIGIN = f'https://dumps.wikimedia.org/wikidatawiki/entities/{DATE}/{DUMP_NAME}'


def _snak(qid=None, kind='value'):
    snak = {'snaktype': kind, 'property': 'P5137', 'datatype': 'wikibase-item'}
    if kind == 'value':
        snak['datavalue'] = {'type': 'wikibase-entityid', 'value': {'entity-type': 'item', 'id': qid}}
    return {'mainsnak': snak, 'rank': 'normal'}


def _sense(sid, gloss, qid=None, kind='value'):
    claims = {}
    if qid is not None or kind != 'value':
        claims['P5137'] = [_snak(qid, kind if qid is not None or kind != 'value' else 'value')]
    return {'id': sid, 'glosses': {'de': {'language': 'de', 'value': gloss}} if gloss else {}, 'claims': claims}


def _form(fid, surface, features):
    return {
        'id': fid,
        'representations': {'de': {'language': 'de', 'value': surface}},
        'grammaticalFeatures': features,
        'claims': {'P443': [{'mainsnak': {
            'snaktype': 'value', 'property': 'P443', 'datatype': 'commonsMedia',
            'datavalue': {'value': 'Geh-pronunciation.ogg', 'type': 'string'},
        }}]},
    }


def _lexeme(lid, lemma, language='Q188', category='Q24905', senses=None, forms=None):
    return {
        'type': 'lexeme', 'id': lid, 'language': language, 'lexicalCategory': category,
        'lemmas': {'de': {'language': 'de', 'value': lemma}},
        'claims': {'P18': [{'mainsnak': {
            'snaktype': 'value', 'property': 'P18', 'datatype': 'commonsMedia',
            'datavalue': {'value': 'Geh-image.jpg', 'type': 'string'},
        }}]},
        'forms': forms if forms is not None else [_form(f'{lid}-F1', lemma, ['Q110786'])],
        'senses': senses if senses is not None else [_sense(f'{lid}-S1', 'to go', 'Q42')],
    }


def _dump_text(entities):
    lines = ['[\n']
    for index, entity in enumerate(entities):
        suffix = ',' if index < len(entities) - 1 else ''
        lines.append(json.dumps(entity, ensure_ascii=False) + suffix + '\n')
    lines.append(']\n')
    return ''.join(lines).encode('utf-8')


def _dump(entities):
    return gzip.compress(_dump_text(entities))


def _multi_member_dump(entities):
    """One JSON array split across two gzip members, as Wikidata dumps are."""
    payload = _dump_text(entities)
    midpoint = max(1, len(payload) // 2)
    return gzip.compress(payload[:midpoint]) + gzip.compress(payload[midpoint:])


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = self.root / 'dist' / 'de-verbs.sqlite'

    def write_dump(self, entities, name=DUMP_NAME, raw=None):
        blob = raw if raw is not None else _dump(entities)
        path = self.root / name
        path.write_bytes(blob)
        digest = hashlib.sha1(blob).hexdigest()
        sums = self.root / f'wikidata-{DATE}-sha1sums.txt'
        sums.write_text(f'{digest}  {name}\n', encoding='utf-8')
        return path, sums

    def extract_dump(self, entities, **kwargs):
        dump, sums = self.write_dump(entities, raw=kwargs.pop('raw', None), name=kwargs.pop('name', DUMP_NAME))
        if 'checksum_text' in kwargs:
            sums.write_text(kwargs.pop('checksum_text'), encoding='utf-8')
        return extract(
            dump, sums, kwargs.pop('blocklist', BLOCKLIST), self.output,
            max_bytes=kwargs.pop('max_bytes', 1024 * 1024),
            max_lexemes=kwargs.pop('max_lexemes', 50),
            dataset_version=DATE, origin_url=ORIGIN, repo_root=self.root, **kwargs)

    def sqlite_text(self):
        return self.output.read_bytes()

    def test_german_verb_is_a_non_production_sqlite_v2_candidate(self):
        before = {
            'sources': (ROOT / 'legal/ledger/sources.json').read_bytes(),
            'manifest': (ROOT / 'manifest.json').read_bytes(),
        }
        report = self.extract_dump([
            _lexeme('L10', 'gehen', senses=[_sense('L10-S1', 'sich fortbewegen', 'Q42')],
                    forms=[_form('L10-F1', 'gehe', ['Q110786', 'Q1317831'])]),
            _lexeme('L11', 'Haus', category='Q1084'),
            _lexeme('L12', 'go', language='Q1860'),
        ])
        self.assertTrue(report['checksum_verified'])
        self.assertFalse(report['publication_approved'])
        self.assertFalse(report['ledger_updated'])
        self.assertEqual(report['written'], 1)
        self.assertEqual((ROOT / 'legal/ledger/sources.json').read_bytes(), before['sources'])
        self.assertEqual((ROOT / 'manifest.json').read_bytes(), before['manifest'])
        blob = self.sqlite_text()
        self.assertNotIn(b'Geh-pronunciation.ogg', blob)
        self.assertNotIn(b'Geh-image.jpg', blob)
        self.assertNotIn(b'P443', blob)
        self.assertNotIn(b'P18', blob)
        with sqlite3.connect(self.output) as conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 2)
            row = conn.execute("SELECT surface, pos, fields_json FROM lexicon").fetchone()
            self.assertEqual(row[0], 'gehen')
            self.assertEqual(row[1], 'verb')
            fields = json.loads(row[2])
            self.assertEqual(fields['morphology']['conjugations'][0]['features']['grammatical_features'],
                             'Q110786,Q1317831')
            definition = conn.execute('SELECT definition FROM senses').fetchone()[0]
            self.assertEqual(definition, 'sich fortbewegen')

    def test_blocked_concepts_are_excluded_and_ambiguous_senses_quarantined(self):
        block = self.root / 'blocklist.json'
        block.write_text(json.dumps({
            'blocked_concepts': ['Q154', 'Q11416', 'Q154136', 'Q11639'],
            'blocked_lemmas': ['tanzen'],
        }), encoding='utf-8')
        report = self.extract_dump([
            _lexeme('L1', 'trinken', senses=[_sense('L1-S1', 'Alkohol trinken', 'Q154')]),
            _lexeme('L2', 'wetten', senses=[_sense('L2-S1', 'um Geld spielen', 'Q11416')]),
            _lexeme('L3', 'lieben', senses=[_sense('L3-S1', 'sexuell begehren', 'Q154136')]),
            _lexeme('L4', 'tanzen', senses=[_sense('L4-S1', 'sich im Tanz bewegen', 'Q11639')]),
            _lexeme('L5', 'gehen', senses=[_sense('L5-S1', 'sich fortbewegen', 'Q42')]),
            _lexeme('L6', 'meinen', senses=[_sense('L6-S1', 'unklar', None, kind='somevalue')]),
            _lexeme('L7', 'setzen', senses=[
                _sense('L7-S1', 'Alkohol', 'Q154'),
                _sense('L7-S2', 'platzieren', 'Q42'),
            ]),
            _lexeme('L8', 'tanzen', senses=[_sense('L8-S1', 'ein anderes Verb', 'Q99')]),
        ], blocklist=block)
        self.assertEqual(report['written'], 1)
        self.assertEqual(report['excluded'], 4)
        self.assertEqual(report['quarantined'], 3)
        excluded = (self.output.with_suffix('.excluded.jsonl')).read_text(encoding='utf-8')
        quarantined = (self.output.with_suffix('.quarantine.jsonl')).read_text(encoding='utf-8')
        for lid in ('L1', 'L2', 'L3', 'L4'):
            self.assertIn(lid, excluded)
        for lid in ('L6', 'L7', 'L8'):
            self.assertIn(lid, quarantined)
        with sqlite3.connect(self.output) as conn:
            lemmas = {row[0] for row in conn.execute('SELECT surface FROM lexicon')}
        self.assertEqual(lemmas, {'gehen'})

    def test_truncated_dump_is_not_checksum_verified(self):
        blob = _dump([_lexeme('L20', 'kommen')])
        report = self.extract_dump([], raw=blob[:max(16, len(blob) // 2)])
        self.assertFalse(report['checksum_verified'])
        self.assertFalse(report['gzip_complete'])
        self.assertTrue(self.output.is_file())

    def test_multi_member_gzip_decompresses_every_member(self):
        entities = [
            _lexeme('L30', 'gehen', senses=[_sense('L30-S1', 'sich fortbewegen', 'Q42')]),
            _lexeme('L31', 'kommen', senses=[_sense('L31-S1', 'ankommen', 'Q43')]),
        ]
        blob = _multi_member_dump(entities)
        self.assertGreaterEqual(blob.count(b'\x1f\x8b'), 2)
        text, complete = gunzip_bytes(blob)
        self.assertTrue(complete)
        self.assertEqual(text.encode('utf-8'), _dump_text(entities))
        report = self.extract_dump([], raw=blob)
        self.assertTrue(report['gzip_complete'])
        self.assertTrue(report['checksum_verified'])
        self.assertEqual(report['written'], 2)
        with sqlite3.connect(self.output) as conn:
            surfaces = {row[0] for row in conn.execute('SELECT surface FROM lexicon')}
        self.assertEqual(surfaces, {'gehen', 'kommen'})

    def test_truncated_later_member_is_incomplete_and_unverified(self):
        entities = [
            _lexeme('L32', 'gehen', senses=[_sense('L32-S1', 'sich fortbewegen', 'Q42')]),
            _lexeme('L33', 'kommen', senses=[_sense('L33-S1', 'ankommen', 'Q43')]),
        ]
        payload = _dump_text(entities)
        midpoint = payload.index(b'\n', 2)
        first = gzip.compress(payload[:midpoint])
        second = gzip.compress(payload[midpoint:])
        self.assertGreater(len(second), 8)
        blob = first + second[:-1]
        text, complete = gunzip_bytes(blob)
        self.assertFalse(complete)
        self.assertIn('gehen', text)
        report = self.extract_dump([], raw=blob)
        self.assertFalse(report['gzip_complete'])
        self.assertFalse(report['checksum_verified'])
        self.assertTrue(self.output.is_file())
        with sqlite3.connect(self.output) as conn:
            rows = conn.execute('SELECT fields_json FROM lexicon').fetchall()
        self.assertTrue(rows)
        for (fields_json,) in rows:
            source = json.loads(fields_json)['source']
            self.assertIsNone(source['artifact_sha256'])

    def test_complete_dump_with_wrong_checksum_is_rejected(self):
        blob = _dump([_lexeme('L21', 'kommen')])
        with self.assertRaises(ExtractError):
            self.extract_dump([], raw=blob, checksum_text='0' * 40 + f'  {DUMP_NAME}\n')
        self.assertFalse(self.output.exists())

    def test_oversize_dump_is_refused(self):
        blob = _dump([_lexeme('L22', 'kommen')])
        with self.assertRaises(ExtractError):
            self.extract_dump([], raw=blob, max_bytes=len(blob) - 1)
        self.assertFalse(self.output.exists())

    def test_production_paths_are_refused(self):
        dump, sums = self.write_dump([_lexeme('L23', 'kommen')])
        with self.assertRaises(ExtractError):
            extract(dump, sums, BLOCKLIST, ROOT / 'packs' / 'de-verbs.sqlite',
                    max_bytes=1024 * 1024, max_lexemes=10, dataset_version=DATE,
                    origin_url=ORIGIN, repo_root=ROOT)
        self.assertFalse((ROOT / 'packs' / 'de-verbs.sqlite').exists())

    def test_out_of_order_sense_id_is_preserved_and_invalid_ids_quarantine(self):
        report = self.extract_dump([
            _lexeme('L10', 'gehen', senses=[_sense('L10-S4', 'sich fortbewegen', 'Q42')]),
            _lexeme('L11', 'kommen', senses=[_sense('L11-S0', 'ankommen', 'Q43')]),
            _lexeme('L12', 'sehen', senses=[_sense('L99-S1', 'wahrnehmen', 'Q44')]),
        ])
        self.assertEqual(report['written'], 1)
        self.assertEqual(report['quarantined'], 2)
        with sqlite3.connect(self.output) as conn:
            row = conn.execute('SELECT sense_id, payload_json FROM senses').fetchone()
        self.assertEqual(row[0], 'sense.de.l10.s4')
        payload = json.loads(row[1])
        self.assertEqual(payload['source']['record_locator'], 'L10-S4')
        quarantined = self.output.with_suffix('.quarantine.jsonl').read_text(encoding='utf-8')
        self.assertIn('L11', quarantined)
        self.assertIn('L12', quarantined)
        self.assertNotIn('L10', quarantined)

    def test_stream_stops_at_max_lexemes_before_later_members(self):
        verb = _lexeme('L40', 'gehen', senses=[_sense('L40-S1', 'sich fortbewegen', 'Q42')])
        head = b'[\n' + json.dumps(verb).encode('utf-8') + b',\n'
        tail = (b'{"type":"item","id":"Q9","labels":{"en":{"value":"' + (b'A' * 200) + b'"}}}\n') * 2000
        tail += b']\n'
        self.assertGreater(len(tail), 400_000)
        blob = gzip.compress(head) + gzip.compress(tail)
        reader = GzipLineReader(io.BytesIO(blob))
        try:
            first = next(line for line in reader if line.strip().startswith('{'))
        finally:
            pulled = reader.decompressed_bytes
            reader.close()
        self.assertIn('L40', first)
        self.assertLess(pulled, len(tail))
        self.assertFalse(reader.gzip_complete)
        report = self.extract_dump([], raw=blob, max_lexemes=1)
        self.assertEqual(report['written'], 1)
        self.assertEqual(report['german_verbs_considered'], 1)
        self.assertFalse(report['gzip_complete'])
        self.assertFalse(report['checksum_verified'])
        self.assertLess(report['decompressed_bytes'], len(tail))
        with sqlite3.connect(self.output) as conn:
            surfaces = {row[0] for row in conn.execute('SELECT surface FROM lexicon')}
        self.assertEqual(surfaces, {'gehen'})

    def test_workflow_is_manual_and_bounded(self):
        text = (ROOT / '.github/workflows/wikidata_de_verbs.yml').read_text(encoding='utf-8')
        self.assertIn('workflow_dispatch:', text)
        self.assertIn('contents: read', text)
        self.assertIn('268435456', text)
        self.assertIn('--max-filesize "$MAX_BYTES"', text)
        self.assertIn("-w '%{http_code}'", text)
        self.assertIn('[ "$http_code" != "206" ]', text)
        self.assertNotIn('git push', text)
        self.assertNotIn('legal/ledger/sources.json', text)
        self.assertNotIn('[skip ci]', text)


if __name__ == '__main__':
    unittest.main()
