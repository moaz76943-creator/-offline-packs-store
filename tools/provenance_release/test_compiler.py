import json
import tempfile
import unittest
from pathlib import Path
import hashlib
from tools.provenance_release.compiler import ProvenanceCompiler, main

def sha256_str(data: str) -> str:
    return hashlib.sha256(data.encode('utf-8')).hexdigest()

class TestProvenanceCompiler(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        self.ledger_path = self.root / 'sources.json'
        self.daily_dir = self.root / 'daily'
        self.daily_dir.mkdir()

        self.manifest_out = self.root / 'release_provenance.json'
        self.notice_out = self.root / 'NOTICE.txt'

        self.compiler = ProvenanceCompiler(self.root, self.ledger_path, self.daily_dir)

        self.artifact_content = "test content"
        self.artifact_sha = sha256_str(self.artifact_content)
        self.artifact_path = self.root / 'artifact.txt'
        self.artifact_path.write_text(self.artifact_content)

        self.notice_content = "src_id publisher CC-BY-SA-4.0 https://origin"
        self.notice_path = self.root / 'notice.txt'
        self.notice_path.write_text(self.notice_content)

        self.base_source = {
            "source_id": "src_id",
            "kind": "dictionary",
            "origin_url": "https://origin",
            "publisher": "publisher",
            "dataset_version": "v1",
            "retrieval": {
                "identity": "id",
                "url": "https://origin/download",
                "date": "2026-01-01",
                "artifact_path": "path",
                "sha256": self.artifact_sha
            },
            "license": {
                "id": "CC-BY-SA-4.0",
                "evidence_url": "https://ev",
                "evidence_path": "ev_path",
                "evidence_sha256": "0"*64
            },
            "status": "APPROVED_FOR_REDISTRIBUTION",
            "alterations": ["none"],
            "review": {
                "reviewer": "me",
                "decision_url": "https://decision"
            }
        }

        self.base_candidate = {
            "asset_id": "asset_1",
            "kind": "dictionary",
            "artifact_path": "artifact.txt",
            "sha256": self.artifact_sha,
            "source_refs": [
                {
                    "source_id": "src_id",
                    "dataset_version": "v1",
                    "artifact_sha256": self.artifact_sha
                }
            ],
            "output_license_id": "CC-BY-SA-4.0",
            "compiler_license_id": "compiler_lic",
            "notices": {
                "src_id": "notice.txt"
            },
            "compliance": {
                "attribution": True
            },
            "provenance_mode": "source_set",
            "record_provenance_reason": "test",
            "review": {
                "reviewer": "me",
                "decision_url": "https://decision"
            }
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_ledger(self, sources):
        self.ledger_path.write_text(json.dumps({"schema_version": "1.0.0", "sources": sources}))

    def write_daily(self, candidates, name="daily.json"):
        (self.daily_dir / name).write_text(json.dumps({
            "schema_version": "1.0.0",
            "date": "2026-01-01",
            "release_candidates": candidates
        }))

    def test_successful_compilation(self):
        self.write_ledger([self.base_source])
        self.write_daily([self.base_candidate])

        statuses = self.compiler.compile(self.manifest_out, self.notice_out)
        self.assertEqual(statuses['approved'], ['asset_1'])
        self.assertEqual(statuses['invalid'], [])

        manifest = json.loads(self.manifest_out.read_text())
        self.assertEqual(len(manifest['release_provenance']), 1)
        self.assertEqual(manifest['release_provenance'][0]['asset_id'], 'asset_1')
        self.assertEqual(manifest['release_provenance'][0]['sources'][0]['publisher'], 'publisher')

    def test_missing_publisher_in_notice(self):
        self.notice_path.write_text("src_id CC-BY-SA-4.0 https://origin") # missing publisher
        self.write_ledger([self.base_source])
        self.write_daily([self.base_candidate])

        statuses = self.compiler.compile(self.manifest_out, self.notice_out)
        self.assertEqual(statuses['invalid'], ['asset_1'])

    def test_missing_author_or_source_id(self):
        # We test that missing author in notice fails
        src = self.base_source.copy()
        src['author'] = "author_name"
        self.notice_path.write_text("src_id publisher CC-BY-SA-4.0 https://origin")
        self.write_ledger([src])
        self.write_daily([self.base_candidate])

        statuses = self.compiler.compile(self.manifest_out, self.notice_out)
        self.assertEqual(statuses['invalid'], ['asset_1'])

        # Now include the author
        self.notice_path.write_text("src_id publisher CC-BY-SA-4.0 https://origin author_name")
        statuses = self.compiler.compile(self.manifest_out, self.notice_out)
        self.assertEqual(statuses['approved'], ['asset_1'])

        manifest = json.loads(self.manifest_out.read_text())
        self.assertEqual(manifest['release_provenance'][0]['sources'][0]['author'], "author_name")

    def test_altered_file_invalid_hash(self):
        self.artifact_path.write_text("altered content") # Changes hash
        self.write_ledger([self.base_source])
        self.write_daily([self.base_candidate])

        statuses = self.compiler.compile(self.manifest_out, self.notice_out)
        self.assertEqual(statuses['invalid'], ['asset_1'])

    def test_mixed_licensing_conflict(self):
        src2 = self.base_source.copy()
        src2['source_id'] = 'src2'
        src2['license'] = src2['license'].copy()
        src2['license']['id'] = 'GFDL-1.3-only'

        cand = self.base_candidate.copy()
        cand['source_refs'] = cand['source_refs'] + [{
            "source_id": "src2",
            "dataset_version": "v1",
            "artifact_sha256": self.artifact_sha
        }]

        self.write_ledger([self.base_source, src2])
        self.write_daily([cand])

        statuses = self.compiler.compile(self.manifest_out, self.notice_out)
        self.assertEqual(statuses['invalid'], ['asset_1'])

    def test_duplicate_provenance(self):
        self.write_ledger([self.base_source])
        self.write_daily([self.base_candidate, self.base_candidate]) # Duplicate

        statuses = self.compiler.compile(self.manifest_out, self.notice_out)
        # The first should be valid (if everything else is fine), second invalid because of duplicate asset_id
        # Actually our implementation will process the first one as valid and second as invalid.
        # But wait, wait: in the compiler, `seen_cids.add(cid)` will mark the second as duplicate.
        self.assertIn('asset_1', statuses['approved'])
        self.assertIn('asset_1', statuses['invalid'])

    def test_blocked_license(self):
        src = self.base_source.copy()
        src['status'] = 'BLOCKED_LICENSE'
        self.write_ledger([src])
        self.write_daily([self.base_candidate])

        statuses = self.compiler.compile(self.manifest_out, self.notice_out)
        self.assertEqual(statuses['blocked'], ['asset_1'])
        self.assertNotIn('asset_1', statuses['approved'])

        manifest = json.loads(self.manifest_out.read_text())
        self.assertIn('asset_1', manifest.get('blocked', []))

    def test_review_required(self):
        src = self.base_source.copy()
        src['status'] = 'REVIEW_REQUIRED'
        self.write_ledger([src])
        self.write_daily([self.base_candidate])

        statuses = self.compiler.compile(self.manifest_out, self.notice_out)
        self.assertEqual(statuses['review_required'], ['asset_1'])
        self.assertNotIn('asset_1', statuses['approved'])

        manifest = json.loads(self.manifest_out.read_text())
        self.assertIn('asset_1', manifest.get('review_required', []))

    def _compile_exit(self):
        return main([
            '--repo-root', str(self.root),
            '--ledger', str(self.ledger_path),
            '--daily-dir', str(self.daily_dir),
            '--manifest-out', str(self.manifest_out),
            '--notice-out', str(self.notice_out),
        ])

    def test_valid_daily_exits_zero(self):
        self.write_ledger([self.base_source])
        self.write_daily([self.base_candidate])
        self.assertEqual(self._compile_exit(), 0)

    def test_unsupported_schema_version_fails_compilation(self):
        self.write_ledger([self.base_source])
        self.write_daily([self.base_candidate], name='good.json')
        (self.daily_dir / 'bad.json').write_text(json.dumps({
            'schema_version': '9.9.9',
            'date': '2026-01-01',
            'release_candidates': [self.base_candidate],
        }))
        statuses = self.compiler.compile(self.manifest_out, self.notice_out)
        self.assertIn('daily[0]', statuses['invalid'])
        self.assertEqual(statuses['approved'], ['asset_1'])
        self.assertEqual(self._compile_exit(), 1)

    def test_non_object_daily_is_invalid(self):
        self.write_ledger([self.base_source])
        (self.daily_dir / 'daily.json').write_text('[1, 2, 3]')
        statuses = self.compiler.compile(self.manifest_out, self.notice_out)
        self.assertEqual(statuses['invalid'], ['daily[0]'])
        self.assertEqual(statuses['approved'], [])
        self.assertEqual(self._compile_exit(), 1)

    def test_non_list_release_candidates_are_invalid(self):
        self.write_ledger([self.base_source])
        (self.daily_dir / 'daily.json').write_text(json.dumps({
            'schema_version': '1.0.0',
            'date': '2026-01-01',
            'release_candidates': {'asset_id': 'asset_1'},
        }))
        statuses = self.compiler.compile(self.manifest_out, self.notice_out)
        self.assertEqual(statuses['invalid'], ['daily[0].release_candidates'])
        self.assertEqual(self._compile_exit(), 1)

    def test_malformed_entries_are_invalid(self):
        self.write_ledger([self.base_source])
        (self.daily_dir / 'daily.json').write_text(json.dumps({
            'schema_version': '1.0.0',
            'date': '2026-01-01',
            'release_candidates': ['nope', {'kind': 'dictionary'}, {'asset_id': '  '}],
        }))
        statuses = self.compiler.compile(self.manifest_out, self.notice_out)
        self.assertEqual(statuses['invalid'], [
            'daily[0].release_candidates[0]',
            'daily[0].release_candidates[1]',
            'daily[0].release_candidates[2]',
        ])
        self.assertEqual(statuses['approved'], [])
        self.assertEqual(self._compile_exit(), 1)

if __name__ == '__main__':
    unittest.main()
