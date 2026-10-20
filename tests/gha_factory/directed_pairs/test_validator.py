"""Synthetic-only direct-link QA. No test text is production learning content."""
import hashlib
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools' / 'gha_factory' / 'directed_pairs'))
from validator import PILOT, PairError, _pin_verified, audit_pairs, main


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def original(sid, lang, text, author='fixture-author'):
    return '\t'.join([sid, lang, text, author, 'fixture-created', 'fixture-updated']) + '\n'


def side(sid, lang, text, license='CC0-1.0'):
    return {'source_id': 'tatoeba', 'sentence_id': sid, 'language': lang,
            'text': text, 'author': 'fixture-author', 'license': license,
            'origin_url': 'https://tatoeba.org/en/sentences/show/' + sid}


def pair(sha, links_sha):
    a, b = '11', '22'
    key = (json.dumps([a, b], sort_keys=True, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
    return {'id': 'pair1_' + digest(key)[:24], 'source': side(a, 'de', 'Haus'),
            'target': side(b, 'ar', 'بيت'), 'link_proof': 'tatoeba_explicit_reciprocal',
            'source_snapshot_sha256': sha, 'links_sha256': links_sha,
            'status': 'VERIFIED_LINK_REVIEW_REQUIRED'}


class PairValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.inputs = {
            'detailed': (original('11', 'deu', 'Haus') + original('22', 'ara', 'بيت')).encode(),
            'links': b'11\t22\n22\t11\n',
            'cc0': b'11\tdeu\tHaus\t2026-10-10 10:00:00\n22\tara\t\xd8\xa8\xd9\x8a\xd8\xaa\t2026-10-10 10:00:01\n',
        }
        self.inputs['candidates'] = (json.dumps(pair(digest(self.inputs['detailed']), digest(self.inputs['links'])), ensure_ascii=False) + '\n').encode()

    def audit(self):
        values = {}
        for key, data in self.inputs.items():
            p = self.dir / (key + '.txt')
            p.write_bytes(data)
            values[key] = (p, digest(data))
        return audit_pairs(*[v for k in ('detailed', 'links', 'cc0', 'candidates') for v in values[k]], dict(PILOT), set(PILOT.values()))

    def mutate(self, **kwargs):
        doc = json.loads(self.inputs['candidates'].decode())
        doc.update(kwargs)
        self.inputs['candidates'] = (json.dumps(doc, ensure_ascii=False) + '\n').encode()

    def test_pinned_copy_ignores_a_later_replacement(self):
        raw = self.inputs['detailed']
        path = self.dir / 'detailed.txt'
        path.write_bytes(raw)
        pinned = _pin_verified(path, digest(raw), self.dir)
        path.write_bytes(b'99\teng\treplaced\tauthor\tcreated\tupdated\n')
        self.assertEqual(pinned.read_bytes(), raw)

    def test_explicit_direct_reciprocal_is_only_review_candidate(self):
        report = self.audit()
        self.assertEqual(1, report['counts']['cc0_direct_candidates_review_required'])
        self.assertFalse(report['publication_approved'])
        self.assertFalse(report['semantic_equivalence_approved'])

    def test_one_way_link_is_not_reciprocal(self):
        self.inputs['links'] = b'11\t22\n'
        self.mutate(links_sha256=digest(self.inputs['links']))
        with self.assertRaisesRegex(PairError, 'NOT_AN_EXPLICIT'):
            self.audit()

    def test_transitive_german_english_arabic_does_not_create_direct_pair(self):
        self.inputs['links'] = b'11\t33\n33\t11\n33\t22\n22\t33\n'
        self.mutate(links_sha256=digest(self.inputs['links']))
        with self.assertRaisesRegex(PairError, 'NOT_AN_EXPLICIT'):
            self.audit()

    def test_forged_original_text_rejected(self):
        doc = json.loads(self.inputs['candidates'].decode())
        doc['target']['text'] = 'نص بديل'
        self.mutate(**doc)
        with self.assertRaisesRegex(PairError, 'SENTENCE_SOURCE_MISMATCH'):
            self.audit()

    def test_license_claim_without_matching_cc0_rejected(self):
        self.inputs['cc0'] = b'11\tdeu\tHaus\t2026-10-10 10:00:00\n'
        with self.assertRaisesRegex(PairError, 'LICENSE_CLAIM_MISMATCH'):
            self.audit()

    def test_non_cc0_candidate_never_marked_approved(self):
        self.inputs['cc0'] = b'11\tdeu\tHaus\t2026-10-10 10:00:00\n'
        doc = json.loads(self.inputs['candidates'].decode())
        doc['target']['license'] = 'CC-BY-2.0-FR'
        self.mutate(**doc)
        result = self.audit()
        self.assertEqual(1, result['counts']['license_review_required'])
        self.assertFalse(result['publication_approved'])

    def test_cc0_last_modified_date_is_not_username(self):
        # Official CC0 export column 4 is Date last modified, not an author.
        # Username belongs to sentences_detailed and must be checked there.
        self.inputs['cc0'] = (b'11\tdeu\tHaus\t2026-10-13 20:00:01\n'
                              b'22\tara\t\xd8\xa8\xd9\x8a\xd8\xaa\t2026-10-13 20:00:02\n')
        result = self.audit()
        self.assertEqual(1, result['counts']['cc0_direct_candidates_review_required'])

    def test_tampered_username_must_be_rejected_against_detailed(self):
        doc = json.loads(self.inputs['candidates'].decode())
        doc['source']['author'] = 'forged-owner'
        self.mutate(**doc)
        with self.assertRaisesRegex(PairError, 'SENTENCE_SOURCE_MISMATCH'):
            self.audit()

    def test_cc0_text_mismatch_cannot_inherit_license(self):
        self.inputs['cc0'] = (b'11\tdeu\tHaus\t2026-10-10 10:00:00\n'
                              b'22\tara\t\xd8\xa8\xd9\x8a\xd8\xaa-CHANGED\t2026-10-10 10:00:01\n')
        with self.assertRaisesRegex(PairError, 'LICENSE_CLAIM_MISMATCH'):
            self.audit()

    def test_tampered_input_sha(self):
        path = self.dir / 'sample.txt'
        path.write_bytes(b'11\t22\n')
        with self.assertRaisesRegex(PairError, 'SOURCE_SHA_MISMATCH'):
            audit_pairs(path, '0'*64, path, digest(path.read_bytes()), path,
                        digest(path.read_bytes()), path, digest(path.read_bytes()), dict(PILOT), set(PILOT.values()))

    def test_wrong_language_and_attribution_rejected(self):
        p = json.loads(self.inputs['candidates'].decode())
        p['source']['language'] = 'en'
        self.mutate(**p)
        with self.assertRaisesRegex(PairError, 'SENTENCE_SOURCE_MISMATCH'):
            self.audit()

    def test_duplicate_pairs_rejected(self):
        self.inputs['candidates'] *= 2
        with self.assertRaisesRegex(PairError, 'DUPLICATE_CANDIDATE_PAIR'):
            self.audit()

    def test_duplicate_json_keys_rejected(self):
        self.inputs['candidates'] = b'{"id":"a","id":"b"}\n'
        with self.assertRaisesRegex(PairError, 'DUPLICATE_JSON_KEY'):
            self.audit()

    def test_wrong_pair_id_rejected(self):
        self.mutate(id='pair1_bad')
        with self.assertRaisesRegex(PairError, 'INVALID_DETERMINISTIC_PAIR_ID'):
            self.audit()

    def test_oversized_line_rejected(self):
        self.inputs['candidates'] = b'"' + b'x'*65536 + b'"\n'
        with self.assertRaisesRegex(PairError, 'BAD_LINE'):
            self.audit()

    def test_invalid_utf8_rejected(self):
        self.inputs['links'] += b'\xff\n'
        with self.assertRaisesRegex(PairError, 'INVALID_ROW'):
            self.audit()

    def test_mapping_must_preserve_canonical_pilot(self):
        with self.assertRaisesRegex(PairError, 'INVALID_CANONICAL_LANGUAGE_MAP'):
            audit_pairs('x', '0'*64, 'x', '0'*64, 'x', '0'*64, 'x', '0'*64,
                        {'deu':'ar', **{k:v for k,v in PILOT.items() if k!='deu'}}, set(PILOT.values()))

    def test_output_tmp_symlink_must_not_overwrite_unrelated_file(self):
        victim = self.dir / 'victim.txt'
        victim.write_text('DO_NOT_OVERWRITE', encoding='utf-8')
        output = self.dir / 'report.json'
        (self.dir / 'report.json.tmp').symlink_to(victim)
        catalog = self.dir / 'manifest.json'
        catalog.write_text(json.dumps({'languages': [{'code': 'x' + str(i)} for i in range(100)]}))
        args = ['--catalog', str(catalog), '--out', str(output)]
        for name in ('detailed', 'links', 'cc0', 'candidates'):
            args.extend(['--' + name, 'irrelevant', '--' + name + '-sha256', 'a'*64])
        with patch('validator.audit_pairs', return_value={'status': 'QA_ONLY_REVIEW_REQUIRED'}):
            with self.assertRaisesRegex(PairError, 'UNSAFE_OUTPUT_PATH'):
                main(args)
        self.assertEqual('DO_NOT_OVERWRITE', victim.read_text(encoding='utf-8'))

    def test_bounded_pair_budget(self):
        with self.assertRaisesRegex(PairError, 'PAIR_BUDGET_EXCEEDED'):
            self.inputs['candidates'] *= 2
            # Budget exceed is reached before duplicate pair detection.
            vals = {}
            for k, data in self.inputs.items():
                p = self.dir / k
                p.write_bytes(data)
                vals[k] = (p, digest(data))
            audit_pairs(*[v for k in ('detailed','links','cc0','candidates') for v in vals[k]], dict(PILOT), set(PILOT.values()), max_pairs=1)


if __name__ == '__main__':
    unittest.main()
