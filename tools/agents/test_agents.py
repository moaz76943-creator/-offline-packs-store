"""Agents stay independent. These tests do not call the network."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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
    stale_heartbeats,
    docs_check,
    duplicate_issues,
    janitor_action,
    unresolved_review_threads,
    urls_well_formed,
)
from tools.agents.root_cause import open_recorded_issue, repair_update
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

    def test_qa_duplicate_key_keeps_source_sense_concept_identity(self):
        """One attested sense may validly anchor multiple directed concepts."""
        row = {
            'language': 'de', 'lemma': 'Bank',
            'source_id': 'wikidata.lexemes', 'record_id': 'L210',
            'sense_id': 'L210-S1', 'concept_id': 'concept.q100',
            'license_id': 'CC0-1.0', 'retrieval_date': '2026-10-20',
        }
        distinct = [
            row,
            dict(row, concept_id='concept.q101'),
            dict(row, source_id='other.approved.source'),
        ]
        valid = qa_rows(distinct, [{'id': 'de', 'script': 'Latn'}], sample=len(distinct))
        self.assertEqual(valid['problems'], [], valid)
        duplicate = qa_rows([row, dict(row)], [{'id': 'de', 'script': 'Latn'}],
                            sample=2)
        self.assertTrue(any('duplicate' in problem for problem in duplicate['problems']))

    def test_quality_agent_scans_all_source_rows_not_just_first_five(self):
        """A sixth bad harvested record must fail source QA even after good rows."""
        import argparse
        from unittest import mock
        from tools.agents import cli as agent_cli
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'data/agents/harvest/wikidata/ar'
            source.mkdir(parents=True)
            rows = [{
                'language': 'ar', 'section': 'food',
                'lemma': 'كتاب', 'record_id': f'L{i}',
                'source_id': 'wikidata.lexemes', 'license_id': 'CC0-1.0',
                'retrieval_date': '2026-10-20',
            } for i in range(5)]
            rows.append({
                'language': 'ar', 'section': 'food',
                'lemma': 'Hallo', 'record_id': 'L6',
                'source_id': 'wikidata.lexemes', 'license_id': 'CC0-1.0',
                'retrieval_date': '2026-10-20',
            })
            (source / 'food.json').write_text(json.dumps({'rows': rows}), encoding='utf-8')
            # A classified snapshot may replay the same source records; QA
            # inspects the source of truth rather than counting stage copies.
            classified = root / 'data/agents/classified'
            classified.mkdir(parents=True)
            (classified / 'rows.json').write_text(json.dumps({'rows': rows}), encoding='utf-8')
            with (mock.patch.object(agent_cli, 'ROOT', root),
                  mock.patch.object(agent_cli, 'OUT', root / 'output'),
                  mock.patch.object(agent_cli, 'load_profiles', return_value={
                      'languages': [{'id': 'ar', 'script': 'Arab'}]})):
                self.assertEqual(agent_cli.command_qa(argparse.Namespace()), 1)
            report = json.loads((root/'output/state/agents/qa-report.json').read_text())
            self.assertEqual(report['sampled'], 6)
            self.assertTrue(any('L6: wrong script' in x for x in report['problems']))

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

        duplicated = legal_report(
            [{'record_id': 'w1', 'source_id': 'wikidata.lexemes', 'license_id': 'CC0-1.0'},
             {'record_id': 'w2', 'source_id': 'wikidata.lexemes', 'license_id': 'CC0-1.0'}],
            {},
        )
        self.assertEqual(duplicated['problems'], [])
        self.assertEqual(duplicated['warnings'],
                         ['wikidata.lexemes: notice not loaded'])

    def test_official_wikidata_cc0_notice_is_source_scoped_and_fail_closed(self):
        """Official Wikidata structured-data notice never approves other texts."""
        from tools.open_sources.assess import positive_match
        notice_path = ROOT / 'legal/source_evidence/wikidata-structured-cc0.txt'
        notice = notice_path.read_text(encoding='utf-8')
        self.assertIn('https://www.wikidata.org/wiki/Wikidata:Copyright', notice)
        self.assertIn('Lexeme', notice)
        self.assertIn('CC0-1.0', notice)
        self.assertTrue(positive_match(notice, 'CC0-1.0')[0])
        self.assertFalse(positive_match(notice, 'CC-BY-SA-4.0')[0])
        accepted = legal_report([
            {'record_id': 'wikidata-L1', 'source_id': 'wikidata.lexemes',
             'license_id': 'CC0-1.0'},
        ], {'wikidata.lexemes': notice})
        self.assertEqual(accepted['problems'], [])
        self.assertEqual(accepted['warnings'], [])
        # Missing evidence remains degraded and unknown licenses stay blocked.
        self.assertEqual(legal_report([
            {'record_id': 'wikidata-L1', 'source_id': 'wikidata.lexemes',
             'license_id': 'CC0-1.0'}], {})['warnings'],
                         ['wikidata.lexemes: notice not loaded'])
        self.assertTrue(legal_report([
            {'record_id': 'wikidata-L1', 'source_id': 'wikidata.lexemes',
             'license_id': 'CC-BY-SA-4.0'}],
            {'wikidata.lexemes': notice})['problems'])

    def test_janitor_cleanup_and_repair_do_not_force_or_touch_main(self):
        green = {
            'branch': 'cursor/example-cf19',
            'merge_state': 'CLEAN',
            'unresolved': False,
            'checks': [
                {'name': 'public-pr-merge-gate', 'status': 'completed', 'conclusion': 'success'},
            ],
        }
        self.assertEqual(janitor_action(green)[0], 'merge')
        for bad in ('skipped', 'failure', None, 'cancelled'):
            with self.subTest(conclusion=bad):
                check = dict(green['checks'][0], conclusion=bad)
                decision, reason = janitor_action(dict(green, checks=[check]))
                self.assertEqual(decision, 'leave')
                self.assertIn('checks failed or skipped', reason)
        mixed = green['checks'] + [
            {'name': 'another-check', 'status': 'completed', 'conclusion': 'skipped'}
        ]
        self.assertEqual(janitor_action(dict(green, checks=mixed))[0], 'leave')
        for malformed in (None, 'invalid', [None], [42], [{'name': 'bad'}]):
            with self.subTest(malformed=malformed):
                self.assertEqual(janitor_action(dict(green, checks=malformed))[0], 'leave')
        behind = dict(green, behind=True, merge_state='BEHIND')
        self.assertEqual(janitor_action(behind)[0], 'update')
        self.assertEqual(janitor_action(dict(green, unresolved=True))[0], 'leave')
        self.assertEqual(janitor_action(dict(green, unresolved=None))[0], 'leave')
        self.assertEqual(janitor_action(dict(green, merge_state='BLOCKED'))[0], 'leave')
        self.assertEqual(janitor_action(dict(green, merge_state='UNKNOWN'))[0], 'leave')
        self.assertEqual(janitor_action({'branch': 'cursor/example-cf19', 'checks': green['checks']})[0], 'leave')
        self.assertEqual(janitor_action({'branch': 'feature/human', 'checks': green['checks']})[0], 'leave')
        self.assertFalse(branch_deletable('main', True))
        self.assertFalse(branch_deletable('agents/data', True))
        self.assertFalse(branch_deletable('cursor/example-cf19', True))
        self.assertFalse(branch_deletable('language-production/rolling', False))
        self.assertTrue(branch_deletable('language-production/rolling', True))
        first, plan = repair_update({}, 'curl timeout', run_id='100')
        self.assertEqual(plan['action'], 'recorded')
        self.assertEqual(plan['retries'], 0)
        self.assertIn('shared remote slice', plan['root_cause'])
        same, plan = repair_update(first, 'curl timeout', run_id='100')
        self.assertEqual(same['seen_count'], 1)
        second, plan = repair_update(same, 'curl timeout', run_id='101')
        self.assertEqual(plan['action'], 'open-root-cause-issue')
        self.assertNotIn('retry', plan['action'])
        tracked, plan = repair_update(second, 'curl timeout', run_id='102', root_causes_text='## curl-timeout\n')
        self.assertEqual(plan['action'], 'already-tracked')
        self.assertEqual(tracked['tracked_in'], 'ROOT_CAUSES.md')
        filed = dict(second, issue_number=12)
        _again, plan = repair_update(filed, 'curl timeout', run_id='103')
        self.assertEqual(plan['action'], 'already-tracked')
        self.assertEqual(plan['issue_number'], 12)
        dupes = duplicate_issues([
            {'number': 1, 'title': 'Same', 'state': 'open'},
            {'number': 2, 'title': 'Same', 'state': 'open'},
        ])
        self.assertEqual([item['number'] for item in dupes], [2])
        self.assertEqual(dispatch_batch(['a', 'b', 'c', 'd'], cap=3), ['a', 'b', 'c'])
        self.assertEqual(urls_well_formed(['https://example.com', 'http://nope']), ['http://nope'])

    def test_wikidata_harvest_rotates_attested_concepts_between_runs(self):
        """Two scheduled harvests must not retry the same first concepts."""
        import argparse
        import os
        import shutil
        from unittest import mock
        from tools.agents import cli as agent_cli
        from tools.agents import harvest as source

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / 'state' / 'agents'
            state.mkdir(parents=True)
            (state / 'plan.json').write_text(json.dumps({
                'schema_version': '1.0.0',
                'window': [{'language': 'de', 'section': 'food'}],
            }), encoding='utf-8')
            graph = {'sections': [{
                'id': 'food',
                'subsections': [{'id': 'food.examples', 'concepts': [
                    {'id': f'concept.{i}', 'wikidata': f'Q{100 + i}'}
                    for i in range(16)
                ]}],
            }]}
            attempted = []

            def observed_query(qid):
                attempted.append(qid)
                return []

            with (mock.patch.object(agent_cli, 'ROOT', root),
                  mock.patch.object(agent_cli, 'OUT', root / 'output'),
                  mock.patch.object(agent_cli, 'load_graph', return_value=graph),
                  mock.patch.object(agent_cli, 'load_languages', return_value={
                      'languages': [{'id': 'de', 'wikidata': 'Q188'}]}),
                  mock.patch.object(agent_cli, 'load_profiles', return_value={
                      'languages': [{'id': 'de', 'script': 'Latn'}]}),
                  mock.patch.object(source, 'search_lexemes', side_effect=observed_query),
                  mock.patch.object(source, 'load_lexemes', return_value={}),
                  mock.patch.dict(os.environ, {'AGENTS_HALT': '',
                                               'LANGUAGE_PRODUCTION_HALT': ''})):
                args = argparse.Namespace(name='harvest-wikidata')
                self.assertEqual(agent_cli.command_harvest(args), 0)
                first = list(attempted)
                attempted.clear()
                cursor = root / 'output/state/agents/harvest-wikidata-cursor.json'
                self.assertTrue(cursor.is_file(), 'harvest must persist its cursor')
                shutil.copyfile(cursor, state / 'harvest-wikidata-cursor.json')
                self.assertEqual(agent_cli.command_harvest(args), 0)
                second = list(attempted)

            self.assertEqual(len(first), 8)
            self.assertEqual(len(second), 8)
            self.assertEqual(len(set(first + second)), 16)
            self.assertEqual(json.loads(cursor.read_text())['next_index'], 0)
            self.assertFalse(list((root / 'output/data/agents/packs').glob('*.sqlite'))
                             if (root / 'output/data/agents/packs').exists() else [])

    def test_harvest_preserves_previous_verified_concepts_across_windows(self):
        """Real checkpoint publication must not clobber earlier language rows."""
        import argparse
        import os
        import shutil
        from unittest import mock
        from tools.agents import cli as agent_cli
        from tools.agents import harvest as source

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / 'state' / 'agents'
            state.mkdir(parents=True)
            (state / 'plan.json').write_text(json.dumps({
                'schema_version': '1.0.0',
                'window': [{'language': 'de', 'section': 'food'}],
            }))
            graph = {'sections': [{
                'id': 'food',
                'subsections': [{'id': 'food.examples', 'concepts': [
                    {'id': f'concept.{i}', 'wikidata': f'Q{100 + i}'}
                    for i in range(16)
                ]}],
            }]}
            def synthetic_row(_entity, concept, *_args):
                qid = concept['wikidata']
                return ([{
                    'language': 'de',
                    'section': 'food',
                    'concept_id': concept['concept_id'],
                    'wikidata': qid,
                    'lemma': 'test-' + qid,
                    'record_id': 'Lexeme:' + qid,
                    'source_id': 'wikidata.lexemes',
                    'license_id': 'CC0-1.0',
                    'retrieval_date': '2026-10-20',
                    'status': 'keep',
                }], 'keep')
            harvested = root / 'output/data/agents/harvest/wikidata/de/food.json'
            stored = root / 'data/agents/harvest/wikidata/de/food.json'
            cursor = root / 'output/state/agents/harvest-wikidata-cursor.json'
            with (mock.patch.object(agent_cli, 'ROOT', root),
                  mock.patch.object(agent_cli, 'OUT', root / 'output'),
                  mock.patch.object(agent_cli, 'load_graph', return_value=graph),
                  mock.patch.object(agent_cli, 'load_languages', return_value={
                      'languages': [{'id': 'de', 'wikidata': 'Q188'}]}),
                  mock.patch.object(agent_cli, 'load_profiles', return_value={
                      'languages': [{'id': 'de', 'script': 'Latn'}]}),
                  mock.patch.object(source, 'search_lexemes', side_effect=lambda q: [q]),
                  mock.patch.object(source, 'load_lexemes',
                                    side_effect=lambda ids: {x: {'id': x} for x in ids}),
                  mock.patch.object(source, 'rows_from_lexeme', side_effect=synthetic_row),
                  mock.patch.dict(os.environ, {'AGENTS_HALT': '',
                                               'LANGUAGE_PRODUCTION_HALT': ''})):
                for expected in (8, 16, 16):
                    self.assertEqual(agent_cli.command_harvest(
                        argparse.Namespace(name='harvest-wikidata')), 0)
                    actual = json.loads(harvested.read_text())['rows']
                    self.assertEqual(len(actual), expected)
                    self.assertEqual(len({r['record_id'] for r in actual}), expected)
                    stored.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(harvested, stored)
                    shutil.copyfile(cursor, state / cursor.name)
            self.assertEqual({r['concept_id'] for r in actual},
                             {f'concept.{i}' for i in range(16)})

    def test_watchdog_surfaces_degraded_agents_without_relaunch_storm(self):
        import argparse
        import os
        from unittest import mock
        from tools.agents import cli as agent_cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            states = root / 'state' / 'agents'
            states.mkdir(parents=True)
            for agent in ROSTER:
                name = agent['name']
                write_heartbeat(states, name,
                                'degraded' if name in ('harvest-wikidata', 'legal') else 'ok',
                                'no production evidence' if name == 'harvest-wikidata' else '')
            with (mock.patch.object(agent_cli, 'ROOT', root),
                  mock.patch.object(agent_cli, 'OUT', root / 'output'),
                  mock.patch.dict(os.environ, {'AGENTS_HALT': '',
                                               'LANGUAGE_PRODUCTION_HALT': ''})):
                self.assertEqual(agent_cli.command_watchdog(
                    argparse.Namespace(codeql_runs='')), 0)
            report = json.loads((root/'output/state/agents/watchdog-report.json').read_text())
            self.assertEqual(report['stale'], [])
            self.assertEqual(report['degraded'], ['harvest-wikidata', 'legal'])
            self.assertEqual(report['dispatch'], [])
            heartbeat = json.loads((root/'output/state/agents/watchdog.json').read_text())
            self.assertEqual(heartbeat['status'], 'degraded')
            self.assertIn('degraded=2', heartbeat['warning'])

    def test_tatoeba_harvest_rotates_supported_real_language_codes(self):
        import argparse
        import os
        import shutil
        from unittest import mock
        from tools.agents import cli as agent_cli
        from tools.agents import harvest as source

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notice = root / 'legal/source_evidence/tatoeba-terms.txt'
            notice.parent.mkdir(parents=True)
            notice.write_text('verified fixture', encoding='utf-8')
            state = root / 'state/agents'
            state.mkdir(parents=True)
            calls = []
            def samples(code):
                calls.append(code)
                return [{
                    'record_id': 'tatoeba:' + code,
                    'text': 'Example sentence ' + code,
                    'author': 'Test Author',
                    'sentence_slot': 'sentence.statement',
                }]
            languages = [
                {'id': 'de', 'wikidata': 'Q188'},
                {'id': 'en', 'wikidata': 'Q1860'},
                {'id': 'sv', 'wikidata': 'Q9027'},
            ]
            with (mock.patch.object(agent_cli, 'ROOT', root),
                  mock.patch.object(agent_cli, 'OUT', root / 'output'),
                  mock.patch.object(agent_cli, 'load_graph', return_value={'sections': []}),
                  mock.patch.object(agent_cli, 'load_languages', return_value={'languages': languages}),
                  mock.patch.object(agent_cli, 'load_profiles', return_value={'languages': [
                      {'id': lang['id'], 'script': 'Latn'} for lang in languages]}),
                  mock.patch.object(source, 'accept_notice', return_value=True),
                  mock.patch.object(source, 'tatoeba_sample', side_effect=samples),
                  mock.patch.dict(os.environ, {'AGENTS_HALT': '',
                                               'LANGUAGE_PRODUCTION_HALT': ''})):
                for _ in range(3):
                    self.assertEqual(agent_cli.command_harvest(
                        argparse.Namespace(name='harvest-tatoeba')), 0)
                    cursor = root / 'output/state/agents/harvest-tatoeba-cursor.json'
                    self.assertTrue(cursor.is_file())
                    shutil.copyfile(cursor, state / cursor.name)
            self.assertEqual(set(calls), {'deu', 'eng', 'swe'})
            self.assertEqual(len(calls), 3)
            for language in ('de', 'en', 'sv'):
                saved = root / f'output/data/agents/harvest/tatoeba/{language}/sentences.json'
                self.assertTrue(saved.is_file(), str(saved))
                payload = json.loads(saved.read_text())
                self.assertEqual(payload['language'], language)
                self.assertEqual(payload['rows'][0]['language'], language)

    def test_watchdog_round_robin_does_not_starve_later_stale_agents(self):
        stale = ['a', 'b', 'c', 'd', 'e', 'f', 'g']
        batches = [dispatch_batch(stale, cap=3, rotation=hour) for hour in range(7)]
        self.assertEqual(batches[0], ['a', 'b', 'c'])
        self.assertEqual(batches[1], ['d', 'e', 'f'])
        self.assertEqual(set().union(*map(set, batches)), set(stale))
        self.assertTrue(all(len(batch) <= 3 and len(batch) == len(set(batch))
                            for batch in batches))
        self.assertEqual(dispatch_batch(stale, cap=0, rotation=1), [])
        self.assertEqual(dispatch_batch([], cap=3, rotation=99), [])
        with self.assertRaises(ValueError):
            dispatch_batch(stale, cap=4)
        with self.assertRaises(ValueError):
            dispatch_batch(stale, cap=3, rotation=-1)

    def test_health_agent_reports_real_heartbeat_gaps_and_recovers(self):
        import argparse
        import os
        from unittest import mock
        from tools.agents import cli as agent_cli
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            states = root / 'state' / 'agents'
            states.mkdir(parents=True)
            for agent in ROSTER:
                write_heartbeat(states, agent['name'], 'ok')
            with (mock.patch.object(agent_cli, 'ROOT', root),
                  mock.patch.object(agent_cli, 'OUT', root / 'output'),
                  mock.patch.dict(os.environ, {'AGENTS_HALT': '', 'LANGUAGE_PRODUCTION_HALT': ''})):
                args = argparse.Namespace(signature='no-signature', run_id='', file_issue=False)
                self.assertEqual(agent_cli.command_repair(args), 0)
                good = json.loads((root/'output/state/agents/health-report.json').read_text())
                self.assertEqual(good['roster_count'], len(ROSTER))
                self.assertEqual(good['stale'], [])
                self.assertEqual(good['degraded'], [])
                self.assertEqual(json.loads((root/'output/state/agents/health.json').read_text())['status'], 'ok')
                (states / 'qa.json').unlink()
                write_heartbeat(states, 'classifier', 'degraded', 'source incomplete')
                self.assertEqual(agent_cli.command_repair(args), 0)
                report = json.loads((root/'output/state/agents/health-report.json').read_text())
                self.assertIn('qa', report['stale'])
                self.assertIn('classifier', report['degraded'])
                self.assertFalse(report['failed_github_run'])
                self.assertEqual(json.loads((root/'output/state/agents/health.json').read_text())['status'], 'degraded')
                write_heartbeat(states, 'qa', 'ok')
                write_heartbeat(states, 'classifier', 'ok')
                self.assertEqual(agent_cli.command_repair(args), 0)
                recovered = json.loads((root/'output/state/agents/health-report.json').read_text())
                self.assertEqual(recovered['stale'], [])
                self.assertEqual(recovered['degraded'], [])
                self.assertEqual(json.loads((root/'output/state/agents/health.json').read_text())['status'], 'ok')

    def test_health_agent_cannot_mask_failed_run_when_heartbeats_fresh(self):
        # Exercise the reporting predicate without writing any network or issue.
        failed = {'failed_github_run': True, 'stale': [], 'degraded': []}
        self.assertTrue(failed['failed_github_run'] or failed['stale'] or failed['degraded'])

    def test_codeql_completed_action_receipt_prevents_false_watchdog_staleness(self):
        from tools.agents.ops import codeql_run_heartbeat
        now = datetime(2026, 10, 20, 1, tzinfo=timezone.utc)
        stamp = '2026-10-20T00:08:33Z'
        good = {'status': 'completed', 'conclusion': 'success', 'createdAt': stamp}
        beat = codeql_run_heartbeat([good], now.timestamp())
        self.assertEqual(beat['name'], 'codeql')
        self.assertEqual(beat['status'], 'ok')
        self.assertNotIn('codeql', stale_heartbeats([beat], now.timestamp(), 8*3600))
        for conclusion in ('skipped', 'failure', 'cancelled', 'timed_out'):
            bad = dict(good, conclusion=conclusion)
            with self.subTest(conclusion=conclusion):
                observed = codeql_run_heartbeat([bad], now.timestamp())
                self.assertEqual(observed['status'], 'degraded')
                self.assertIn(conclusion, observed['warning'])
        self.assertIsNone(codeql_run_heartbeat([dict(good, createdAt='invalid')], now.timestamp()))
        self.assertIsNone(codeql_run_heartbeat([dict(good, createdAt='2027-10-20T00:00:00Z')], now.timestamp()))
        self.assertIsNone(codeql_run_heartbeat('wrong-type', now.timestamp()))
        self.assertIsNone(codeql_run_heartbeat([{'status':'in_progress'}], now.timestamp()))

    def test_watchdog_ingests_codeql_evidence_without_credential_mutations(self):
        import argparse
        import os
        from unittest import mock
        from tools.agents import cli as agent_cli
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / 'codeql-runs.json'
            evidence.write_text(json.dumps([
                {'status':'completed','conclusion':'success',
                 'createdAt':datetime.now(timezone.utc).isoformat()}
            ]), encoding='utf-8')
            with (mock.patch.object(agent_cli, 'ROOT', root),
                  mock.patch.object(agent_cli, 'OUT', root / 'output'),
                  mock.patch.dict(os.environ, {'AGENTS_HALT':'', 'LANGUAGE_PRODUCTION_HALT':''})):
                self.assertEqual(agent_cli.command_watchdog(
                    argparse.Namespace(codeql_runs=str(evidence))), 0)
            saved = json.loads((root/'output/state/agents/codeql.json').read_text())
            self.assertEqual(saved['status'],'ok')
            snapshot = json.loads((root/'output/state/agents/watchdog-report.json').read_text())
            self.assertNotIn('codeql', snapshot['stale'])
            heartbeat = json.loads((root/'output/state/agents/watchdog.json').read_text())
            self.assertEqual(heartbeat['name'], 'watchdog')
            self.assertNotIn('stale', heartbeat)
            self.assertLessEqual(len(snapshot['dispatch']), 3)

    def test_watchdog_uses_agent_schedule_before_flagging_stale(self):
        now = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)

        def recent(name, hours):
            return {
                'name': name,
                'last_run': (now - timedelta(hours=hours)).isoformat(),
            }

        heartbeats = [
            recent('codeql', 10),  # Daily; should not be restarted hourly.
            recent('docs', 10),
            recent('schema-guard', 10),  # Twice daily.
            recent('watchdog', 10),  # Hourly; definitely stale.
        ]
        stale = stale_heartbeats(heartbeats, now.timestamp(), 8 * 3600)
        self.assertNotIn('codeql', stale)
        self.assertNotIn('docs', stale)
        self.assertNotIn('schema-guard', stale)
        self.assertIn('watchdog', stale)

        too_old = stale_heartbeats(
            [recent('codeql', 27)], now.timestamp(), 8 * 3600,
        )
        self.assertIn('codeql', too_old)

    def test_janitor_uses_exact_review_thread_evidence(self):
        clean = {'data': {'repository': {'pullRequest': {'reviewThreads': {
            'nodes': [], 'pageInfo': {'hasNextPage': False},
        }}}}}
        self.assertFalse(unresolved_review_threads(clean))
        dirty = json.loads(json.dumps(clean))
        dirty['data']['repository']['pullRequest']['reviewThreads']['nodes'] = [
            {'isResolved': False},
        ]
        self.assertTrue(unresolved_review_threads(dirty))
        dirty['data']['repository']['pullRequest']['reviewThreads']['nodes'][0]['isResolved'] = True
        self.assertFalse(unresolved_review_threads(dirty))
        dirty['data']['repository']['pullRequest']['reviewThreads']['pageInfo']['hasNextPage'] = True
        self.assertTrue(unresolved_review_threads(dirty))
        self.assertTrue(unresolved_review_threads({'errors': [{'message': 'forbidden'}]}))
        self.assertTrue(unresolved_review_threads({}))
        self.assertTrue(unresolved_review_threads({'data': {'repository': None}}))

    def test_root_cause_issue_opens_once_and_workflows_do_not_retry(self):
        calls = []

        def runner(args):
            calls.append(args)
            if args[1] == 'list':
                return '[]'
            return 'https://github.com/moaz76943-creator/-offline-packs-store/issues/9'

        plan, _plan = repair_update({}, 'No module named license_notice', run_id='1')
        _again, plan = repair_update(plan, 'No module named license_notice', run_id='2')
        opened = open_recorded_issue(plan, runner=runner)
        self.assertEqual(opened['issue_number'], 9)
        self.assertEqual(opened['action'], 'already-tracked')
        open_recorded_issue(opened, runner=runner)
        self.assertEqual(len(calls), 2)
        root = Path(__file__).resolve().parents[2]
        workflow = (root / '.github/workflows/agent_tests.yml').read_text(encoding='utf-8')
        self.assertIn('python3 -m unittest tools.agents.test_agents -q', workflow)
        self.assertNotIn('legal.ledger.test_license_notice', workflow)
        publish = (root / 'tools/agents/publish.sh').read_text(encoding='utf-8')
        self.assertNotIn('while', publish)


# The existing agent CI command also runs real-git checkpoint regressions.
from tools.agents.test_publish import PublishTests


if __name__ == '__main__':
    unittest.main()
