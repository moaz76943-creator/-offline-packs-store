"""Agents stay independent. These tests do not call the network."""

import json
import tempfile
import unittest
from pathlib import Path

from tools.agents.common import (
    halted,
    is_placeholder,
    load_json_tolerant,
    script_matches,
    write_heartbeat,
)
from tools.agents.ops import (
    branch_deletable,
    dispatch_batch,
    docs_check,
    duplicate_issues,
    janitor_action,
    repair_update,
    urls_well_formed,
)
from tools.agents.roster import ROSTER
from tools.agents.work import (
    build_pack,
    classify_row,
    coverage,
    grammar_for_language,
    legal_report,
    next_window,
    qa_rows,
    shard_pairs,
    tune,
)
from tools.language_production.catalog import ROOT


class ContractTests(unittest.TestCase):
    def test_kill_switch_and_malformed_state(self):
        self.assertTrue(halted({'AGENTS_HALT': 'true'}))
        self.assertTrue(halted({'LANGUAGE_PRODUCTION_HALT': 'true'}))
        self.assertFalse(halted({'AGENTS_HALT': 'false'}))
        self.assertFalse(halted({}))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'missing.json'
            value, warning = load_json_tolerant(path, {'schema_version': '1.0.0'})
            self.assertEqual(warning, 'missing')
            self.assertEqual(value['schema_version'], '1.0.0')
            path.write_text('{', encoding='utf-8')
            _value, warning = load_json_tolerant(path, {'schema_version': '1.0.0'})
            self.assertEqual(warning, 'malformed')
            path.write_text(json.dumps({'schema_version': '0.0.1'}), encoding='utf-8')
            _value, warning = load_json_tolerant(path, {'schema_version': '1.0.0'})
            self.assertEqual(warning, 'stale_or_malformed')
            write_heartbeat(tmp, 'qa', 'ok')
            saved = json.loads((Path(tmp) / 'qa.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['status'], 'ok')
            self.assertEqual(saved['schema_version'], '1.0.0')

    def test_roster_workflows_exist_and_are_independent(self):
        report = docs_check(ROOT)
        self.assertEqual(report['missing'], [], report['missing'])
        self.assertGreaterEqual(len(ROSTER), 20)
        groups = set()
        for agent in ROSTER:
            text = (ROOT / agent['workflow']).read_text(encoding='utf-8')
            self.assertNotIn('needs:', text)
            self.assertIn(f"group: agent-{agent['name']}", text)
            groups.add(agent['name'])
        self.assertEqual(len(groups), len(ROSTER))

    def test_planner_is_rule_based_and_coverage_comes_from_rows(self):
        self.assertEqual(tune({'schema_version': '0'})['reason'].startswith('default'), True)
        grown = tune({
            'schema_version': '1.0.0',
            'runs': [{'status': 'ok', 'duration_seconds': 30}] * 3,
        })
        self.assertEqual(grown['max_parallel'], 20)
        shrunk = tune({
            'schema_version': '1.0.0',
            'runs': [{'status': 'failed', 'duration_seconds': 30}] * 3,
        })
        self.assertLess(shrunk['max_parallel'], 20)
        pairs = shard_pairs(['ar', 'de'], ['food', 'home'])
        window, nxt, warning = next_window(pairs, {'next_index': 3}, 2)
        self.assertEqual(warning, '')
        self.assertEqual(len(window), 2)
        self.assertEqual(nxt, 1)
        _window, _nxt, warning = next_window(pairs, {'next_index': 'nope'}, 2)
        self.assertEqual(warning, 'malformed cursor')
        graph = {'sections': [{'id': 'food', 'subsections': [{'id': 'food.q1', 'concepts': [
            {'id': 'concept.q1', 'wikidata': 'Q1'},
        ]}]}]}
        report = coverage(graph, [{
            'language': 'de', 'concept_id': 'concept.q1', 'lemma': 'Essen',
            'source_id': 'wikidata.lexemes', 'record_id': 'L1', 'license_id': 'CC0-1.0',
            'retrieval_date': '2026-10-18',
        }], ['de', 'ar'])
        self.assertEqual(report['concepts'], 1)
        german = next(row for row in report['languages'] if row['id'] == 'de')
        arabic = next(row for row in report['languages'] if row['id'] == 'ar')
        self.assertEqual(german['filled'], 1)
        self.assertEqual(arabic['gaps'], 1)

    def test_rows_must_be_traceable_and_policy_clean(self):
        self.assertTrue(is_placeholder('TODO'))
        self.assertFalse(script_matches('طعام', 'Latn'))
        self.assertTrue(script_matches('طعام', 'Arab'))
        index = {'Q1': {'concept_id': 'concept.q1', 'section': 'food', 'subsection': 'food.q1'}}
        placed = classify_row({
            'language': 'ar', 'lemma': 'طعام', 'wikidata': 'Q1', 'qids': ['Q1'],
            'source_id': 'wikidata.lexemes', 'record_id': 'L9', 'license_id': 'CC0-1.0',
            'retrieval_date': '2026-10-18',
        }, index)
        self.assertEqual(placed['status'], 'keep')
        self.assertIn('estimated:heuristic-v1', placed['level']['evidence'])
        blocked = classify_row({
            'language': 'ar', 'lemma': 'خمر', 'wikidata': 'Q154', 'qids': ['Q154'],
            'source_id': 'wikidata.lexemes', 'record_id': 'L8', 'license_id': 'CC0-1.0',
            'retrieval_date': '2026-10-18',
        }, index)
        self.assertEqual(blocked['status'], 'exclude')
        fake = classify_row({
            'language': 'en', 'lemma': 'TODO', 'wikidata': 'Q1',
            'source_id': 'wikidata.lexemes', 'record_id': 'L7', 'license_id': 'CC0-1.0',
            'retrieval_date': '2026-10-18',
        }, index)
        self.assertEqual(fake['status'], 'reject')
        problems = qa_rows([
            placed,
            dict(placed, record_id='L9'),
        ], [{'id': 'ar', 'script': 'Latn'}], sample=2)
        self.assertTrue(any('wrong script' in item or 'duplicate' in item for item in problems['problems']))

    def test_grammar_uses_profile_facts_and_packs_need_rows(self):
        payload = grammar_for_language({'id': 'ar', 'script': 'Arab', 'direction': 'rtl'}, [])
        self.assertEqual({slot['id'] for slot in payload['slots']}, {'grammar.script', 'grammar.direction'})
        with tempfile.TemporaryDirectory() as tmp:
            empty = build_pack([], Path(tmp) / 'empty.sqlite')
            self.assertFalse(empty['wrote'])
            written = build_pack([{
                'language': 'de', 'concept_id': 'concept.q1', 'lemma': 'Essen',
                'source_id': 'wikidata.lexemes', 'record_id': 'L1', 'license_id': 'CC0-1.0',
                'retrieval_date': '2026-10-18',
            }], Path(tmp) / 'de.sqlite')
            self.assertTrue(written['wrote'])
            self.assertEqual(len(written['sha256']), 64)

    def test_legal_blocks_a_real_conflict_only(self):
        clean = legal_report(
            [{
                'record_id': 'L1', 'source_id': 'kaikki.wiktextract', 'license_id': 'CC-BY-SA-4.0',
                'co_offered': ['GFDL-1.3-only'],
            }],
            {'kaikki.wiktextract': (ROOT / 'legal/source_evidence/wiktionary-copyrights.txt').read_text(encoding='utf-8')},
        )
        self.assertEqual(clean['problems'], [])
        dirty = legal_report(
            [{'record_id': 'x', 'source_id': 'apertium', 'license_id': 'CC-BY-SA-4.0'}],
            {'apertium': (ROOT / 'legal/source_evidence/apertium-eng-copying.txt').read_text(encoding='utf-8')},
        )
        self.assertTrue(dirty['problems'])
        missing = legal_report(
            [{'record_id': 'x', 'source_id': 'omegawiki', 'license_id': 'CC0-1.0'}],
            {},
        )
        self.assertEqual(missing['problems'], [])
        self.assertTrue(missing['warnings'])

    def test_janitor_cleanup_and_repair_do_not_force_or_touch_main(self):
        green = {
            'branch': 'cursor/example-cf19',
            'checks': [
                {'name': 'public-pr-merge-gate', 'status': 'completed', 'conclusion': 'success'},
            ],
        }
        self.assertEqual(janitor_action(green)[0], 'merge')
        behind = dict(green, behind=True)
        self.assertEqual(janitor_action(behind)[0], 'update')
        self.assertEqual(janitor_action({'branch': 'feature/human', 'checks': green['checks']})[0], 'leave')
        self.assertFalse(branch_deletable('main', True))
        self.assertFalse(branch_deletable('agents/data', True))
        self.assertFalse(branch_deletable('cursor/example-cf19', True))
        self.assertFalse(branch_deletable('language-production/rolling', False))
        self.assertTrue(branch_deletable('language-production/rolling', True))
        state, plan = repair_update({}, 'curl timeout')
        state, plan = repair_update(state, 'curl timeout')
        state, plan = repair_update(state, 'curl timeout')
        self.assertEqual(plan['action'], 'record-and-continue')
        dupes = duplicate_issues([
            {'number': 1, 'title': 'Same', 'state': 'open'},
            {'number': 2, 'title': 'Same', 'state': 'open'},
        ])
        self.assertEqual([item['number'] for item in dupes], [2])
        self.assertEqual(dispatch_batch(['a', 'b', 'c', 'd'], cap=3), ['a', 'b', 'c'])
        self.assertEqual(urls_well_formed(['https://example.com', 'http://nope']), ['http://nope'])


if __name__ == '__main__':
    unittest.main()
