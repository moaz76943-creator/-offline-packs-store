"""Deterministic, offline candidate-only content QA tests."""
import json
import tempfile
import unittest
from pathlib import Path
from tools.content_safety_audit.audit import (load_policy, review_item, audit_candidates,
                                              privacy_inventory, manifest_audit, scan_jsonl)

POLICY = Path(__file__).resolve().parents[2] / 'tools/content_safety_audit/policy.json'


class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = load_policy(POLICY)

    def item(self, text='Das Haus', **kw):
        base = dict(item_id='synthetic-01', media_type='text', source_language='de',
                    target_language='ar', source_text=text)
        base.update(kw)
        return base

    def test_normal_vocabulary_is_allowed_for_qa_only(self):
        r = review_item(self.item(source_text='Das Haus', target_text='البيت'), self.policy)
        self.assertEqual(r['decision'], 'ALLOW')
        self.assertFalse(r['publication_approved'])

    def test_exact_owner_excluded_term_is_rejected_without_deletion(self):
        r = review_item(self.item('خمر', target_text='alcohol', source_language='ar',
                                  target_language='en', sense_id='alcoholic_beverage'), self.policy)
        self.assertEqual(r['decision'], 'REJECT')
        self.assertEqual(r['reason_codes'], ['OWNER_EXCLUDED_SENSE'])

    def test_negated_educational_context_uses_human_review(self):
        r = review_item(self.item('لا تشرب الخمر', target_text='Do not drink alcohol',
                                  source_language='ar', target_language='en'), self.policy)
        self.assertEqual(r['decision'], 'HUMAN_REVIEW')
        self.assertIn('AMBIGUOUS_EXCLUDED_TERM', r['reason_codes'])

    def test_arabic_diacritics_preserve_sense_distinction(self):
        r = review_item(self.item('خُمُر', source_language='ar', target_language='en',
                                  target_text='head coverings'), self.policy)
        self.assertNotEqual(r['decision'], 'REJECT')

    def test_homograph_bank_is_not_rejected(self):
        r = review_item(self.item('Bank', target_text='مقعد'), self.policy)
        self.assertEqual(r['decision'], 'ALLOW')

    def test_metaphorical_or_derivative_is_not_blocked_by_substring(self):
        r = review_item(self.item('سرقتني ابتسامته', source_language='ar', target_language='en',
                                  target_text='His smile stole my attention'), self.policy)
        self.assertNotEqual(r['decision'], 'REJECT')

    def test_flagged_ambiguous_lexeme_defers_review(self):
        r = review_item(self.item('سرقة', source_language='ar', target_language='en',
                                  target_text='theft'), self.policy)
        self.assertEqual(r['decision'], 'HUMAN_REVIEW')

    def test_missing_pair_metadata_is_not_silently_assumed(self):
        r = review_item(dict(item_id='synthetic-02', media_type='text', source_text='house'), self.policy)
        self.assertEqual(r['decision'], 'HUMAN_REVIEW')
        self.assertIn('MISSING_LANGUAGE_PAIR', r['reason_codes'])

    def test_imagery_with_explicit_inappropriate_tag_rejects(self):
        r = review_item(dict(item_id='synthetic-03', media_type='image', tags=['nudity'],
                             source_language='en', target_language='ar'), self.policy)
        self.assertEqual(r['decision'], 'REJECT')
        self.assertEqual(r['rights_status'], 'EVIDENCE_REQUIRED')

    def test_synthetic_people_image_needs_independent_review(self):
        r = review_item(dict(item_id='synthetic-04', media_type='image', tags=['person'],
                             source_language='ar', target_language='de'), self.policy)
        self.assertEqual(r['decision'], 'HUMAN_REVIEW')
        self.assertIn('IMAGE_VISUAL_REVIEW_REQUIRED', r['reason_codes'])

    def test_image_without_pixels_does_not_claim_inspection(self):
        r = review_item(dict(item_id='synthetic-05', media_type='image', tags=['tree'],
                             source_language='ar', target_language='en'), self.policy)
        self.assertEqual(r['decision'], 'HUMAN_REVIEW')
        self.assertIn('MEDIA_NOT_INSPECTED', r['reason_codes'])

    def test_audio_transcript_is_scanned_but_waveform_unverified(self):
        r = review_item(dict(item_id='synthetic-06', media_type='audio', source_language='ar',
                             target_language='de', transcript='Hallo'), self.policy)
        self.assertEqual(r['decision'], 'HUMAN_REVIEW')
        self.assertIn('MEDIA_NOT_INSPECTED', r['reason_codes'])

    def test_rights_are_separate_from_safety(self):
        r = review_item(self.item('Haus', license_id='CC0-1.0', license_review='approved'), self.policy)
        self.assertEqual(r['decision'], 'ALLOW')
        self.assertEqual(r['rights_status'], 'EVIDENCE_REQUIRED')
        self.assertFalse(r['publication_approved'])

    def test_malformed_or_sensitive_input_is_never_accepted(self):
        r = review_item(self.item('Haus', learner_id='real-user-123'), self.policy)
        self.assertEqual(r['decision'], 'REJECT')
        self.assertIn('LEARNER_DATA_IN_CANDIDATE', r['reason_codes'])
        self.assertNotIn('real-user-123', json.dumps(r))

    def test_privacy_inventory_reports_only_paths_and_no_payload(self):
        r = privacy_inventory(['assets/content/pack.json', 'users/learner_srs.db',
                               'lib/reading.dart'])
        self.assertEqual(r['status'], 'HUMAN_REVIEW')
        self.assertEqual(r['flagged_count'], 1)
        self.assertNotIn('learner_srs.db', json.dumps(r))

    def test_permission_scan_is_read_only_and_contextual(self):
        xml = '<manifest xmlns:android="http://schemas.android.com/apk/res/android"><uses-permission android:name="android.permission.RECORD_AUDIO"/></manifest>'
        r = manifest_audit(xml)
        self.assertEqual(r['status'], 'HUMAN_REVIEW')
        self.assertIn('android.permission.RECORD_AUDIO', r['permissions_to_review'])

    def test_invalid_manifest_is_unknown(self):
        r = manifest_audit('not an xml')
        self.assertEqual(r['status'], 'UNKNOWN')

    def test_stream_counts_are_actual_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'records.jsonl'
            p.write_text('\n'.join([json.dumps(self.item('Haus')),
                                    json.dumps(self.item('سرقة', source_language='ar', target_language='en'))])+'\n')
            r = scan_jsonl(p, self.policy)
            self.assertEqual(r['counts'], {'ALLOW': 1, 'HUMAN_REVIEW': 1, 'REJECT': 0})
            self.assertEqual(r['total'], 2)
            self.assertFalse(r['publication_approved'])

    def test_invalid_record_is_counted_reject_and_no_raw_echo(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'records.jsonl'
            p.write_text('{invalid secret data}\n')
            r = scan_jsonl(p, self.policy)
            self.assertEqual(r['counts']['REJECT'], 1)
            self.assertNotIn('secret data', json.dumps(r))

    def test_missing_media_type_is_review(self):
        r = review_item(dict(item_id='synthetic-08', source_language='en', target_language='ar',
                             source_text='house'), self.policy)
        self.assertEqual(r['decision'], 'HUMAN_REVIEW')

    def test_result_ids_are_never_echoed_without_sanitizing(self):
        r = review_item(dict(item_id='user@email.com', media_type='text',
                             source_language='en', target_language='ar', source_text='house'), self.policy)
        self.assertNotIn('user@email.com', json.dumps(r))

    def test_unknown_language_is_not_claimed_screened(self):
        r = review_item(self.item('葡萄酒', source_language='zh', target_language='de'), self.policy)
        self.assertEqual(r['decision'], 'HUMAN_REVIEW')
        self.assertIn('LANGUAGE_SCREENING_NOT_CONFIGURED', r['reason_codes'])

    def test_hostile_language_type_never_crashes_or_leaks(self):
        r = review_item(self.item('Haus', source_language=['ar']), self.policy)
        self.assertEqual(r['decision'], 'HUMAN_REVIEW')
        self.assertIn('INVALID_LANGUAGE_CODE', r['reason_codes'])

    def test_example_language_and_meaning_are_examined(self):
        r = review_item(self.item('house', examples=[{'language': 'ar', 'text': 'لا تشرب الخمر'}]), self.policy)
        self.assertEqual(r['decision'], 'HUMAN_REVIEW')
        self.assertIn('AMBIGUOUS_EXCLUDED_TERM', r['reason_codes'])

    def test_missing_example_locale_needs_review(self):
        r = review_item(self.item('Haus', examples=[{'text': 'خمر'}]), self.policy)
        self.assertEqual(r['decision'], 'HUMAN_REVIEW')
        self.assertIn('MISSING_EXAMPLE_LANGUAGE', r['reason_codes'])

    def test_translation_direction_is_not_implicitly_reversed(self):
        r = review_item(self.item('Haus', source_language='de', target_language='ar',
                                  translations=[{'language': 'ar', 'text': 'منزل'}]), self.policy)
        self.assertEqual(r['decision'], 'ALLOW')

    def test_nested_learner_identifier_is_detected(self):
        r = review_item(self.item('Haus', metadata={'context': {'user_id': 'private'}}), self.policy)
        self.assertEqual(r['decision'], 'REJECT')
        self.assertNotIn('private', json.dumps(r))

    def test_bad_policy_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'p.json'
            p.write_text('{"schema_version":"bad"}')
            with self.assertRaises(ValueError):
                load_policy(p)


if __name__ == '__main__':
    unittest.main()
