import json
import os
import shutil
import tempfile
import unittest
import hashlib
import zipfile
from tools.open_export.exporter import CommunityExporter, ExportState

class TestCommunityExporter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.source_dir = os.path.join(self.temp_dir, "source")
        self.output_dir = os.path.join(self.temp_dir, "output")
        self.prev_dir = os.path.join(self.temp_dir, "prev")

        os.makedirs(self.source_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.prev_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def write_file(self, path, content):
        with open(path, 'w') as f:
            f.write(content)

    def write_bin_file(self, path, content):
        with open(path, 'wb') as f:
            f.write(content)

    def test_successful_export(self):
        # Create a valid source file
        lex_file = os.path.join(self.source_dir, "lexicon_es.json")
        self.write_file(lex_file, '{"hello": "hola"}')
        h = hashlib.sha256(b'{"hello": "hola"}').hexdigest()

        manifest = {
            "items": [
                {
                    "id": "lex_es_01",
                    "filename": "lexicon_es.json",
                    "type": "lexicon",
                    "lang_pair": "en-es",
                    "license": "CC0-1.0",
                    "evidence": "approved_by_admin",
                    "sha256": h,
                    "provenance": "Community User A"
                }
            ]
        }
        self.write_file(os.path.join(self.source_dir, "manifest.json"), json.dumps(manifest))

        exporter = CommunityExporter(self.source_dir, self.output_dir)
        state = exporter.run()

        self.assertEqual(state, ExportState.READY)
        self.assertTrue(os.path.exists(os.path.join(self.output_dir, "lex_es_01.zip")))
        self.assertTrue(os.path.exists(os.path.join(self.output_dir, "manifest.json")))

        # Verify deterministic zip building
        with zipfile.ZipFile(os.path.join(self.output_dir, "lex_es_01.zip"), 'r') as z:
            self.assertIn("lexicon_es.json", z.namelist())
            self.assertIn("ATTRIBUTION.txt", z.namelist())
            attr = z.read("ATTRIBUTION.txt").decode()
            self.assertIn("CC0-1.0", attr)
            self.assertIn("Community User A", attr)

            # Check deterministic timestamps
            zinfo = z.getinfo("lexicon_es.json")
            self.assertEqual(zinfo.date_time, (2024, 1, 1, 0, 0, 0))

    def test_missing_evidence_blocks_export(self):
        lex_file = os.path.join(self.source_dir, "lexicon_de.json")
        self.write_file(lex_file, '{}')
        h = hashlib.sha256(b'{}').hexdigest()

        manifest = {
            "items": [
                {
                    "id": "lex_de_01",
                    "filename": "lexicon_de.json",
                    "type": "lexicon",
                    "lang_pair": "en-de",
                    "license": "CC0-1.0",
                    "sha256": h,
                    "provenance": "Community User B"
                    # missing evidence
                }
            ]
        }
        self.write_file(os.path.join(self.source_dir, "manifest.json"), json.dumps(manifest))

        exporter = CommunityExporter(self.source_dir, self.output_dir)
        state = exporter.run()
        self.assertEqual(state, ExportState.BLOCKED)
        self.assertFalse(os.path.exists(os.path.join(self.output_dir, "lex_de_01.zip")))

    def test_invalid_license_blocks_export(self):
        lex_file = os.path.join(self.source_dir, "lexicon_fr.json")
        self.write_file(lex_file, '{}')
        h = hashlib.sha256(b'{}').hexdigest()

        manifest = {
            "items": [
                {
                    "id": "lex_fr_01",
                    "filename": "lexicon_fr.json",
                    "type": "lexicon",
                    "lang_pair": "en-fr",
                    "license": "CUSTOM-NON-COMMERCIAL",
                    "evidence": "approved",
                    "sha256": h,
                    "provenance": "User C"
                }
            ]
        }
        self.write_file(os.path.join(self.source_dir, "manifest.json"), json.dumps(manifest))

        exporter = CommunityExporter(self.source_dir, self.output_dir)
        state = exporter.run()
        self.assertEqual(state, ExportState.BLOCKED)

    def test_stale_hash_fails_export(self):
        lex_file = os.path.join(self.source_dir, "lexicon_it.json")
        self.write_file(lex_file, '{"a":"b"}')

        manifest = {
            "items": [
                {
                    "id": "lex_it_01",
                    "filename": "lexicon_it.json",
                    "type": "lexicon",
                    "lang_pair": "en-it",
                    "license": "CC0-1.0",
                    "evidence": "approved",
                    "sha256": "badhash00000000",
                    "provenance": "User D"
                }
            ]
        }
        self.write_file(os.path.join(self.source_dir, "manifest.json"), json.dumps(manifest))

        exporter = CommunityExporter(self.source_dir, self.output_dir)
        state = exporter.run()
        self.assertEqual(state, ExportState.FAILED)

    def test_exclude_private_learner_progress(self):
        prog_file = os.path.join(self.source_dir, "progress.json")
        self.write_file(prog_file, '{}')
        h = hashlib.sha256(b'{}').hexdigest()

        manifest = {
            "items": [
                {
                    "id": "prog_01",
                    "filename": "progress.json",
                    "type": "learner_progress",
                    "license": "CC0-1.0",
                    "evidence": "approved",
                    "sha256": h
                }
            ]
        }
        self.write_file(os.path.join(self.source_dir, "manifest.json"), json.dumps(manifest))

        exporter = CommunityExporter(self.source_dir, self.output_dir)
        state = exporter.run()
        self.assertEqual(state, ExportState.READY)
        # Should be excluded, so manifest shouldn't contain it
        with open(os.path.join(self.output_dir, "manifest.json")) as f:
            out_man = json.load(f)
            self.assertNotIn("prog_01", out_man["artifacts"])

    def test_damaged_vector(self):
        vec_file = os.path.join(self.source_dir, "icon.vct")
        self.write_bin_file(vec_file, b'') # Empty/damaged
        h = hashlib.sha256(b'').hexdigest()

        manifest = {
            "items": [
                {
                    "id": "vec_01",
                    "filename": "icon.vct",
                    "type": "vector",
                    "license": "CC0-1.0",
                    "evidence": "approved",
                    "sha256": h
                }
            ]
        }
        self.write_file(os.path.join(self.source_dir, "manifest.json"), json.dumps(manifest))

        exporter = CommunityExporter(self.source_dir, self.output_dir)
        state = exporter.run()
        self.assertEqual(state, ExportState.FAILED)

    def test_incremental_unchanged(self):
        lex_file = os.path.join(self.source_dir, "lexicon_ru.json")
        self.write_file(lex_file, '{"ru":"ru"}')
        h = hashlib.sha256(b'{"ru":"ru"}').hexdigest()

        manifest = {
            "items": [
                {
                    "id": "lex_ru_01",
                    "filename": "lexicon_ru.json",
                    "type": "lexicon",
                    "lang_pair": "en-ru",
                    "license": "CC0-1.0",
                    "evidence": "approved",
                    "sha256": h
                }
            ]
        }
        self.write_file(os.path.join(self.source_dir, "manifest.json"), json.dumps(manifest))

        # Initial run
        exporter = CommunityExporter(self.source_dir, self.prev_dir)
        self.assertEqual(exporter.run(), ExportState.READY)

        # Second run with prev_dir (source file unmodified)
        exporter2 = CommunityExporter(self.source_dir, self.output_dir, self.prev_dir)
        self.assertEqual(exporter2.run(), ExportState.READY)

        # Verify it used the cached version (unchanged event emitted)
        self.assertTrue(any(e["event"] == "unchanged" and e["artifact"] == "lex_ru_01" for e in exporter2.events))

    def test_invalid_path_fails(self):
        lex_file = os.path.join(self.source_dir, "bad.json")
        self.write_file(lex_file, '{"a":"b"}')

        manifest = {
            "items": [
                {
                    "id": "bad_01",
                    "filename": "../bad.json",
                    "type": "lexicon",
                    "license": "CC0-1.0",
                    "evidence": "approved",
                    "sha256": "anything"
                }
            ]
        }
        self.write_file(os.path.join(self.source_dir, "manifest.json"), json.dumps(manifest))

        exporter = CommunityExporter(self.source_dir, self.output_dir)
        state = exporter.run()
        self.assertEqual(state, ExportState.FAILED)

    def test_repeated_export_idempotency(self):
        # Create a valid source file
        lex_file = os.path.join(self.source_dir, "lexicon_es.json")
        self.write_file(lex_file, '{"hello": "hola"}')
        h = hashlib.sha256(b'{"hello": "hola"}').hexdigest()

        manifest = {
            "items": [
                {
                    "id": "lex_es_01",
                    "filename": "lexicon_es.json",
                    "type": "lexicon",
                    "lang_pair": "en-es",
                    "license": "CC0-1.0",
                    "evidence": "approved_by_admin",
                    "sha256": h,
                    "provenance": "Community User A"
                }
            ]
        }
        self.write_file(os.path.join(self.source_dir, "manifest.json"), json.dumps(manifest))

        exporter1 = CommunityExporter(self.source_dir, self.output_dir)
        self.assertEqual(exporter1.run(), ExportState.READY)

        # Read the hash of the generated zip safely
        with open(os.path.join(self.output_dir, "lex_es_01.zip"), 'rb') as f:
            hash1 = hashlib.sha256(f.read()).hexdigest()

        exporter2 = CommunityExporter(self.source_dir, self.output_dir)
        self.assertEqual(exporter2.run(), ExportState.READY)

        with open(os.path.join(self.output_dir, "lex_es_01.zip"), 'rb') as f:
            hash2 = hashlib.sha256(f.read()).hexdigest()

        self.assertEqual(hash1, hash2)

    def test_restart_preserves_valid_release(self):
        lex_file = os.path.join(self.source_dir, "lexicon_de.json")
        self.write_file(lex_file, '{"de": "de"}')
        h = hashlib.sha256(b'{"de": "de"}').hexdigest()

        manifest = {
            "items": [
                {
                    "id": "lex_de_01",
                    "filename": "lexicon_de.json",
                    "type": "lexicon",
                    "lang_pair": "en-de",
                    "license": "CC0-1.0",
                    "evidence": "approved_by_admin",
                    "sha256": h,
                    "provenance": "Community User A"
                }
            ]
        }
        self.write_file(os.path.join(self.source_dir, "manifest.json"), json.dumps(manifest))

        # valid run
        exporter1 = CommunityExporter(self.source_dir, self.output_dir)
        self.assertEqual(exporter1.run(), ExportState.READY)

        self.assertTrue(os.path.exists(os.path.join(self.output_dir, "lex_de_01.zip")))
        self.assertTrue(os.path.exists(os.path.join(self.output_dir, "manifest.json")))

        # make source bad to fail second run
        manifest["items"][0]["license"] = "BAD-LICENSE"
        self.write_file(os.path.join(self.source_dir, "manifest.json"), json.dumps(manifest))

        exporter2 = CommunityExporter(self.source_dir, self.output_dir)
        self.assertEqual(exporter2.run(), ExportState.BLOCKED)

        # original files should still exist
        self.assertTrue(os.path.exists(os.path.join(self.output_dir, "lex_de_01.zip")))
        self.assertTrue(os.path.exists(os.path.join(self.output_dir, "manifest.json")))


if __name__ == "__main__":
    unittest.main()
