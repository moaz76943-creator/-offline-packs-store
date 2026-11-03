"""Regression coverage for backlogs larger than one REST page and CI-event prioritization."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from coordinator import GitHub, is_candidate_qualified
from auto_run import discovery_order, triggered_check_pr


class ReadyDiscoveryTests(unittest.TestCase):
    def test_qualification_ignores_skip_text_and_rejects_wrong_base(self):
        record = self.candidate(1, False)
        record.update(title='fix: explain [skip ci]', body='[skip ci] is documentation')
        self.assertTrue(is_candidate_qualified(record)[0])
        for changed in ({'draft': True}, {'state': 'closed'}, {'base': {'ref': 'other'}}):
            self.assertFalse(is_candidate_qualified({**record, **changed})[0])

    @staticmethod
    def gh_with_pages(pages):
        gh = object.__new__(GitHub)
        calls = []
        def get(path):
            calls.append(path)
            page = int(path.rsplit('page=', 1)[-1])
            return pages.get(page, [])
        gh.get = get
        return gh, calls

    @staticmethod
    def candidate(number, draft):
        return {
            'number': number, 'state': 'open', 'draft': draft,
            'head': {'sha': format(number, '040x')},
            'base': {'ref': 'main', 'sha': 'a' * 40},
        }

    def test_ready_behind_four_hundred_drafts_is_found(self):
        drafts = [self.candidate(n, True) for n in range(500, 100, -1)]
        pages = {
            1: drafts[:100], 2: drafts[100:200],
            3: drafts[200:300], 4: drafts[300:400],
            5: [self.candidate(1, False)],
        }
        gh, calls = self.gh_with_pages(pages)
        selected = gh.ready_pull_requests()
        self.assertEqual([p['number'] for p in selected], [1])
        self.assertEqual(len(calls), 5)
        self.assertEqual(calls[-1], '/pulls?state=open&base=main&per_page=100&page=5')

    def test_full_last_page_fails_closed_rather_than_hide_old_candidates(self):
        pages = {1: [self.candidate(n, True) for n in range(1, 101)],
                 2: [self.candidate(n, True) for n in range(101, 201)]}
        gh, calls = self.gh_with_pages(pages)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            gh.ready_pull_requests(max_pages=2)
        self.assertEqual(len(calls), 2)

    def test_malformed_page_and_malformed_candidate_fail_closed(self):
        for pages in ({1: {'items': []}}, {1: [{'draft': False}]}):
            with self.subTest(pages=pages):
                gh, _ = self.gh_with_pages(pages)
                with self.assertRaises(ValueError):
                    gh.ready_pull_requests()

    def test_duplicate_pages_do_not_reschedule_same_pr(self):
        pages = {1: [self.candidate(n, False) for n in range(1, 101)],
                 2: [self.candidate(100, False), self.candidate(101, False)]}
        gh, _ = self.gh_with_pages(pages)
        selected = gh.ready_pull_requests()
        self.assertEqual(len(selected), 101)
        self.assertEqual(len({p['number'] for p in selected}), 101)


class PriorityTests(unittest.TestCase):
    def test_completed_gate_event_prioritizes_older_ready_candidate(self):
        payload = {'workflow_run': {
            'name': 'Public PR Merge Gate', 'conclusion': 'success',
            'pull_requests': [{'number': 1}],
        }}
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8') as tmp:
            json.dump(payload, tmp)
            tmp.flush()
            with patch.dict(os.environ, {
                'GITHUB_EVENT_NAME': 'workflow_run',
                'GITHUB_EVENT_PATH': tmp.name,
            }):
                priority = triggered_check_pr()
                self.assertEqual(priority, 1)
                queue = [{'number': n, 'draft': False} for n in range(1, 91)]
                window, deferred = discovery_order(queue, now=0, budget=40, priority=priority)
                self.assertEqual(window[0]['number'], 1)
                self.assertEqual(len(window), 40)
                self.assertEqual(deferred, 50)

    def test_invalid_or_unsuccessful_event_never_inserts_priority(self):
        for payload in (
            {'workflow_run': {'name': 'Public PR Merge Gate',
                              'conclusion': 'failure', 'pull_requests': [{'number': 1}]}},
            {'workflow_run': {'name': 'Unknown workflow',
                              'conclusion': 'success', 'pull_requests': [{'number': 1}]}},
            {'workflow_run': {'name': 'Public PR Merge Gate',
                              'conclusion': 'success', 'pull_requests': [{'number': 1}, {'number': 2}]}},
        ):
            with self.subTest(payload=payload):
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8') as tmp:
                    json.dump(payload, tmp)
                    tmp.flush()
                    with patch.dict(os.environ, {
                        'GITHUB_EVENT_NAME': 'workflow_run',
                        'GITHUB_EVENT_PATH': tmp.name,
                    }):
                        self.assertIsNone(triggered_check_pr())


if __name__ == '__main__':
    unittest.main()
