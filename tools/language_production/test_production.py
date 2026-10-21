"""Language-generic production. Fixtures only; no network and no ledger edits."""

import gzip
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tools.language_production.build_overlay import concept_index
from tools.language_production.catalog import ROOT, load_languages, load_sections, registry_by_id
from tools.language_production.checkpoint import advance_cursor, byte_range, load_cursor
from tools.language_production.dumps import latest_dump_date, resolve_dump_date
from tools.language_production.harvest import (
    assert_safe_output,
    classify_entity,
    harvest_dump,
    harvest_language,
)
from tools.language_production.levels import estimate_level
from tools.language_production.publish import merge_decision
from tools.language_production.repair import note_failure, plan_repair, slice_budget
from tools.language_production.schedule import enabled_languages, rotation_slot, select_batch, select_coverage_batch
from tools.language_production.sections import section_for_items
from tools.language_production.source_gate import issues_to_close, missing_issue_titles, owner_approved
from tools.language_production.status_report import render_status

DATE = '20261014'
ORIGIN = f'https://dumps.wikimedia.org/wikidatawiki/entities/{DATE}/wikidata-{DATE}-lexemes.json.gz'
WORKFLOW = ROOT / '.github' / 'workflows' / 'language_production.yml'
REPORT = ROOT / 'tools' / 'language_production' / 'report.sh'

PROOF = {
    'de': 'Q188',
    'ar': 'Q13955',
    'en': 'Q1860',
    'fr': 'Q150',
    'es': 'Q1321',
    'tr': 'Q256',
}


def _snak(qid=None, kind='value'):
    snak = {'snaktype': kind, 'property': 'P5137', 'datatype': 'wikibase-item'}
    if kind == 'value':
        snak['datavalue'] = {'type': 'wikibase-entityid', 'value': {'entity-type': 'item', 'id': qid}}
    return {'mainsnak': snak, 'rank': 'normal'}


def _sense(lid, number, gloss, language_id, qid=None, kind='value'):
    claims = {}
    if qid is not None or kind != 'value':
        claims['P5137'] = [_snak(qid, kind if qid is not None or kind != 'value' else 'value')]
    glosses = {}
    if gloss:
        glosses[language_id] = {'language': language_id, 'value': gloss}
    return {'id': f'{lid}-S{number}', 'glosses': glosses, 'claims': claims}


def _forms(lid, language_id, surfaces):
    forms = []
    for index, surface in enumerate(surfaces, start=1):
        forms.append({
            'id': f'{lid}-F{index}',
            'representations': {language_id: {'language': language_id, 'value': surface}},
            'grammaticalFeatures': ['Q110786'],
        })
    return forms


def _lexeme(lid, language_qid, language_id, lemma, category='Q1084', senses=None, forms=None):
    return {
        'type': 'lexeme',
        'id': lid,
        'language': language_qid,
        'lexicalCategory': category,
        'lemmas': {language_id: {'language': language_id, 'value': lemma}},
        'forms': forms if forms is not None else _forms(lid, language_id, [lemma]),
        'senses': senses if senses is not None else [_sense(lid, 1, lemma, language_id, 'Q2095')],
    }


def _dump_bytes(entities, extra=b''):
    lines = ['[\n']
    for index, entity in enumerate(entities):
        suffix = ',' if index < len(entities) - 1 or extra else ''
        lines.append(json.dumps(entity, ensure_ascii=False) + suffix + '\n')
    if not extra:
        lines.append(']\n')
    first = ''.join(lines).encode('utf-8')
    if not extra:
        return gzip.compress(first), len(first)
    blob = gzip.compress(first) + gzip.compress(extra)
    return blob, len(first) + len(extra)


class CatalogTests(unittest.TestCase):
    def test_languages_are_registry_ids_with_unique_items(self):
        catalog = load_languages()
        registry = registry_by_id()
        ids = [row['id'] for row in catalog['languages']]
        qids = [row['wikidata'] for row in catalog['languages']]
        self.assertGreaterEqual(len(ids), 70)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(qids), len(set(qids)))
        self.assertTrue(set(ids) <= set(registry))
        self.assertEqual(catalog['proof_languages'], ['de', 'ar', 'en', 'fr', 'es', 'tr'])
        self.assertIn('not a measured dump count', catalog['priority_basis'])
        self.assertEqual(catalog['max_parallel'], 20)
        self.assertGreaterEqual(catalog['batch_size'], 2)

    def test_sections_come_from_classes_not_lemma_text(self):
        taxonomy = load_sections()
        self.assertEqual(section_for_items(['Q2095'], {}, taxonomy), 'food')
        self.assertEqual(section_for_items(['Q100'], {'Q100': {'p31': ['Q2095'], 'p279': []}}, taxonomy), 'food')
        self.assertEqual(section_for_items(['Q1'], {}, taxonomy), 'unclassified')
        self.assertEqual(section_for_items([], {}, taxonomy), 'unclassified')

    def test_level_estimate_is_labelled(self):
        short = estimate_level('gehen', 4, 1)
        self.assertEqual(short['level_id'], 'A1')
        self.assertIn('estimated:heuristic-v1', short['evidence'])
        self.assertIn('not a corpus frequency list', short['evidence'])
        self.assertEqual(estimate_level('house', 1, 1)['level_id'], 'B1')
        self.assertEqual(estimate_level('x' * 18, 0, 1)['level_id'], 'C1')


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.taxonomy = load_sections()
        self.language = {'id': 'de', 'wikidata': 'Q188', 'registry': {'default_script': 'Latn'}}
        self.blocked = {'Q154', 'Q11416', 'Q154136', 'Q11639'}

    def _classify(self, entity, class_index=None):
        return classify_entity(
            entity, self.language, self.taxonomy, class_index or {},
            self.blocked, set(), DATE, ORIGIN,
        )

    def test_blocked_ancestor_is_excluded_and_mixed_is_quarantined(self):
        blocked = _lexeme('L10', 'Q188', 'de', 'wein', senses=[_sense('L10', 1, 'wine', 'de', 'Q9')])
        decision, _payload = self._classify(blocked, {'Q9': {'p31': ['Q154'], 'p279': []}})
        self.assertEqual(decision, 'exclude')
        mixed = _lexeme('L11', 'Q188', 'de', 'haus', senses=[
            _sense('L11', 1, 'house', 'de', 'Q2095'),
            _sense('L11', 2, 'wine', 'de', 'Q9'),
        ])
        decision, payload = self._classify(mixed, {'Q9': {'p31': ['Q154'], 'p279': []}})
        self.assertEqual(decision, 'quarantine')
        self.assertEqual(payload['reason'], 'mixed_blocked_and_allowed_senses')

    def test_out_of_order_sense_id_is_kept(self):
        entity = _lexeme(
            'L12', 'Q188', 'de', 'gehen', category='Q24905',
            senses=[_sense('L12', 4, 'to go', 'de', 'Q2095')],
            forms=_forms('L12', 'de', ['gehe', 'gehst', 'geht', 'gehen']),
        )
        decision, payload = self._classify(entity)
        self.assertEqual(decision, 'keep')
        self.assertEqual(payload['senses'][0]['sense_id'], 'sense.de.l12.s4')
        self.assertEqual(payload['senses'][0]['source']['record_locator'], 'L12-S4')

    def test_bad_sense_id_and_other_language_are_not_kept(self):
        bad = _lexeme('L13', 'Q188', 'de', 'haus', senses=[{'id': 'L13-S0', 'glosses': {}, 'claims': {}}])
        self.assertEqual(self._classify(bad)[0], 'quarantine')
        other = _lexeme('L14', 'Q1860', 'en', 'house')
        self.assertEqual(self._classify(other)[0], 'skip')

    def test_modal_verb_uses_the_class_walk(self):
        entity = _lexeme(
            'L15', 'Q188', 'de', 'koennen', category='Q560570',
            senses=[_sense('L15', 1, 'can', 'de', 'Q2095')],
            forms=_forms('L15', 'de', ['kann', 'koennen']),
        )
        index = {'Q560570': {'p31': [], 'p279': ['Q24905']}}
        decision, payload = self._classify(entity, index)
        self.assertEqual(decision, 'keep')
        self.assertEqual(payload['lexeme']['pos'], 'verb')
        self.assertEqual(payload['senses'][0]['subdomains'], ['verb.modal'])


class OverlayTests(unittest.TestCase):
    def test_proof_languages_share_concepts_and_write_no_pair_database(self):
        taxonomy = load_sections()
        entities = []
        for index, (language_id, qid) in enumerate(PROOF.items(), start=1):
            lid = f'L{100 + index}'
            lemma = 'كتاب' if language_id == 'ar' else language_id + 'wort'
            entities.append(_lexeme(lid, qid, language_id, lemma, senses=[
                _sense(lid, 1, lemma, language_id, 'Q2095'),
            ]))
        blob, _full = _dump_bytes(entities)
        concepts = set()
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / 'slice.json.gz'
            dump.write_bytes(blob)
            for language_id, qid in PROOF.items():
                output = Path(tmp) / f'{language_id}.sqlite'
                summary = harvest_language(
                    dump,
                    {'id': language_id, 'wikidata': qid},
                    taxonomy=taxonomy,
                    class_index={},
                    dataset_version=DATE,
                    origin_url=ORIGIN,
                    max_lexemes=5,
                    output=output,
                    repo_root=tmp,
                )
                self.assertEqual(summary['lexemes'], 1)
                self.assertFalse(summary['checksum_verified'])
                self.assertEqual(summary['pair_databases'], 0)
                self.assertTrue(output.is_file())
                connection = sqlite3.connect(output)
                try:
                    self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 2)
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM translations').fetchone()[0], 0)
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM examples').fetchone()[0], 0)
                    self.assertEqual(
                        connection.execute('SELECT level_assignment FROM grammar').fetchone()[0],
                        'estimated',
                    )
                    direction, script = connection.execute(
                        'SELECT direction, script FROM lexicon'
                    ).fetchone()
                    concept = connection.execute('SELECT concept_id FROM senses').fetchone()[0]
                finally:
                    connection.close()
                concepts.add(concept)
                if language_id == 'ar':
                    self.assertEqual((direction, script), ('rtl', 'Arab'))
                else:
                    self.assertEqual(direction, 'ltr')
                index_path = output.with_suffix('.concepts.json')
                payload = json.loads(index_path.read_text(encoding='utf-8'))
                self.assertEqual(payload['pair_databases'], 0)
                self.assertEqual(payload['concepts'], [concept])
        self.assertEqual(concepts, {'concept.q2095'})

    def test_empty_language_writes_nothing_and_refuses_packs(self):
        taxonomy = load_sections()
        blob, _full = _dump_bytes([_lexeme('L1', 'Q1860', 'en', 'house')])
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / 'slice.json.gz'
            dump.write_bytes(blob)
            output = Path(tmp) / 'de.sqlite'
            summary = harvest_language(
                dump, {'id': 'de', 'wikidata': 'Q188'}, taxonomy=taxonomy, class_index={},
                dataset_version=DATE, origin_url=ORIGIN, max_lexemes=5, output=output, repo_root=tmp,
            )
            self.assertEqual(summary['lexemes'], 0)
            self.assertFalse(output.exists())
            with self.assertRaises(ValueError):
                assert_safe_output(ROOT / 'packs' / 'de.sqlite')
            with self.assertRaises(ValueError):
                assert_safe_output(ROOT / 'legal' / 'ledger' / 'sources.json')

    def test_early_stop_does_not_decompress_the_rest(self):
        taxonomy = load_sections()
        entity = _lexeme('L20', 'Q188', 'de', 'haus')
        extra = (b'{"id":"L21","padding":"' + (b'x' * 100000) + b'"}\n')
        blob, full = _dump_bytes([entity], extra=extra)
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / 'slice.json.gz'
            dump.write_bytes(blob)
            output = Path(tmp) / 'de.sqlite'
            summary = harvest_language(
                dump, {'id': 'de', 'wikidata': 'Q188'}, taxonomy=taxonomy, class_index={},
                dataset_version=DATE, origin_url=ORIGIN, max_lexemes=1, output=output, repo_root=tmp,
            )
            self.assertLess(summary['decompressed_bytes'], full)
            self.assertFalse(summary['gzip_complete'])
            self.assertFalse(summary['checksum_verified'])

    def test_harvest_dump_uses_the_injected_class_fetch(self):
        taxonomy = load_sections()
        blob, _full = _dump_bytes([_lexeme('L30', 'Q188', 'de', 'haus')])
        seen = {}

        def fetch(qids, **_kwargs):
            seen['qids'] = list(qids)
            return {'Q2095': {'p31': [], 'p279': []}}

        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / 'slice.json.gz'
            dump.write_bytes(blob)
            output = Path(tmp) / 'de.sqlite'
            summary = harvest_dump(
                dump, {'id': 'de', 'wikidata': 'Q188'}, taxonomy=taxonomy,
                dataset_version=DATE, origin_url=ORIGIN, max_lexemes=5, output=output,
                fetch=fetch, repo_root=tmp,
            )
        self.assertEqual(summary['lexemes'], 1)
        self.assertIn('Q2095', seen['qids'])
        self.assertEqual(concept_index([{'senses': [{'concept_id': 'concept.q2095'}]}])['pair_databases'], 0)


class ScheduleRepairTests(unittest.TestCase):
    def test_rotation_wraps_and_keeps_later_languages(self):
        catalog = load_languages()
        rows = enabled_languages(catalog)
        batch = select_batch(catalog, 0)
        self.assertEqual([row['id'] for row in batch], ['en', 'fr', 'de'])
        wrapped = select_batch(catalog, len(rows) - 1, batch_size=3)
        self.assertEqual(wrapped[0]['id'], rows[-1]['id'])
        self.assertEqual(wrapped[1]['id'], rows[0]['id'])
        self.assertEqual(rotation_slot(catalog, '', today=date(2026, 1, 1)), 1 % len(rows))
        small = {'batch_size': 2, 'languages': [
            {'id': 'en', 'priority': 1, 'enabled': True},
            {'id': 'fr', 'priority': 2, 'enabled': True},
            {'id': 'de', 'priority': 3, 'enabled': True},
        ]}
        coverage = {'languages': [
            {'id': 'en', 'gap_count': 1},
            {'id': 'fr', 'gap_count': 10},
            {'id': 'de', 'gap_count': 50},
        ]}
        ranked = select_coverage_batch(small, 0, coverage, batch_size=2)
        self.assertEqual([row['id'] for row in ranked], ['de', 'fr'])

    def test_repair_stops_after_two_attempts(self):
        first = plan_repair('curl timeout', 0)
        self.assertEqual(first['action'], 'retry-smaller-slice')
        self.assertEqual(first['attempts'], 1)
        state, second = note_failure({}, 'curl timeout')
        state, third = note_failure(state, 'curl timeout')
        self.assertEqual(second['attempts'], 1)
        self.assertEqual(third['action'], 'retry-smaller-slice')
        state, stopped = note_failure(state, 'curl timeout')
        self.assertEqual(stopped['action'], 'record-and-continue')
        self.assertEqual(stopped['attempts'], 2)
        self.assertEqual(plan_repair('mystery', 0)['action'], 'record-and-continue')
        self.assertEqual(slice_budget(2097152, {'pending_factor': 0.5}), 1048576)

    def test_owner_gate_and_merge_decision(self):
        self.assertTrue(owner_approved([
            {'user': 'moaz76943-creator', 'body': 'please\ndecision: approve\n'},
        ]))
        self.assertFalse(owner_approved([
            {'user': 'someone-else', 'body': 'decision: approve'},
            {'login': 'moaz76943-creator', 'body': 'decision: approved'},
        ]))
        self.assertEqual(missing_issue_titles(['Source decision: Tatoeba']), [])
        self.assertEqual(
            issues_to_close(['Source decision: Tatoeba', 'unrelated']),
            ['Source decision: Tatoeba'],
        )
        checks = [
            {'name': 'public-pr-merge-gate', 'status': 'completed', 'conclusion': 'success'},
            {'name': 'test', 'status': 'completed', 'conclusion': 'skipped'},
        ]
        self.assertTrue(merge_decision(checks, 0)[0])
        self.assertFalse(merge_decision(checks, 1)[0])
        self.assertFalse(merge_decision(checks, 0, halt=True)[0])

    def test_checkpoint_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'cursor.json'
            self.assertEqual(load_cursor(path)['next_offset'], 0)
            advance_cursor(path, dump_date=DATE, downloaded_bytes=100)
            self.assertEqual(byte_range(100, 50), (100, 149))
            wrapped = advance_cursor(path, dump_date=DATE, downloaded_bytes=5, wrapped=True)
            self.assertEqual(wrapped['next_offset'], 5)
        text = render_status({})
        self.assertIn('LANGUAGE_PRODUCTION_HALT', text)
        self.assertIn('decision: approve', text)
        self.assertIn('estimated:heuristic-v1', text)

    def test_dump_date_parser(self):
        html = '<a href="../">../</a><a href="20261014/">20261014/</a><a href="20261016/">20261016/</a>'
        self.assertEqual(latest_dump_date(html), '20261016')
        self.assertEqual(resolve_dump_date('20261014', html), '20261014')
        self.assertEqual(resolve_dump_date('', html), '20261016')


class WorkflowTests(unittest.TestCase):
    def test_schedule_is_bounded_and_does_not_redispatch(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        report = REPORT.read_text(encoding='utf-8')
        harvest = (ROOT / '.github/workflows/agent_harvest_wikidata.yml').read_text(encoding='utf-8')
        self.assertIn("cron: '7 0,6,12,18 * * *'", harvest)
        self.assertIn('workflow_dispatch', text)
        self.assertIn('ubuntu-latest', text)
        self.assertIn('max-parallel: 2', text)
        self.assertIn('LANGUAGE_PRODUCTION_HALT', text)
        self.assertIn("--max-filesize \"$MAX_BYTES\"", text)
        self.assertIn('206', text)
        self.assertIn('contents: read', text)
        self.assertNotIn('gemini', text.casefold())
        self.assertNotIn('[skip ci]', text.casefold())
        self.assertNotIn('workflow run', text)
        self.assertNotIn('gh workflow run', report)
        self.assertNotIn('gemini', report.casefold())
        self.assertIn('decision: approve', report)
        self.assertIn('language-production/rolling', report)
        self.assertIn("refs/heads/main", text)
