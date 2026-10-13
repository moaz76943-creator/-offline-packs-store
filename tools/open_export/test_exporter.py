import base64
import gzip
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

EXPORTER_SCRIPT = Path(__file__).parent / 'exporter.py'

def create_mock_pack(db_content, version="1.0.0", pack_id="de"):
    envelope = {
        "packId": pack_id,
        "version": version,
        "files": [
            {
                "path": "content/content.sqlite",
                "contentBase64": base64.b64encode(db_content).decode('ascii')
            }
        ]
    }
    return gzip.compress(json.dumps(envelope).encode('utf-8'))

def create_mock_db(lexicon_data, translations_data=None):
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        with sqlite3.connect(tmp.name) as conn:
            conn.execute("CREATE TABLE lexicon(id TEXT, surface TEXT, part_of_speech TEXT, direction TEXT, language_code TEXT, source_json TEXT)")
            for row in lexicon_data:
                conn.execute("INSERT INTO lexicon VALUES (?, ?, ?, ?, ?, ?)", row)

            if translations_data is not None:
                conn.execute("CREATE TABLE translations(translation_id TEXT, from_sense_id TEXT, to_sense_id TEXT, language TEXT, text TEXT, source_json TEXT)")
                for row in translations_data:
                    conn.execute("INSERT INTO translations VALUES (?, ?, ?, ?, ?, ?)", row)
        tmp.flush()
        with open(tmp.name, 'rb') as f:
            content = f.read()
    Path(tmp.name).unlink()
    return content

class TestOpenExporter(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.manifest_path = self.root / 'manifest.json'
        self.packs_dir = self.root / 'packs'
        self.packs_dir.mkdir()
        self.dest_zip = self.root / 'out.zip'

    def tearDown(self):
        self.tmpdir.cleanup()

    def run_exporter(self, manifest=None, language="de", categories="lexical", destination=None):
        cmd = [
            sys.executable, str(EXPORTER_SCRIPT),
            '--manifest', str(manifest or self.manifest_path),
            '--language', language,
            '--categories', categories,
            '--destination', str(destination or self.dest_zip)
        ]
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_blocked_repository_access(self):
        # Missing manifest
        res = self.run_exporter(manifest=self.root / 'missing.json')
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("BLOCKED_REPOSITORY_ACCESS", res.stderr)

        # Bad JSON
        self.manifest_path.write_text("{bad", encoding='utf-8')
        res = self.run_exporter()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("BLOCKED_REPOSITORY_ACCESS", res.stderr)

        # Wrong IP status
        self.manifest_path.write_text(json.dumps({"intellectual_property_status": "RESTRICTED"}), encoding='utf-8')
        res = self.run_exporter()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("BLOCKED_REPOSITORY_ACCESS", res.stderr)

    def test_incomplete_source_and_missing_attribution(self):
        self.manifest_path.write_text(json.dumps({
            "intellectual_property_status": "PUBLIC_DOMAIN_ZERO_COPYRIGHT",
            "packs": [{"id": "de", "version": "1.0.0", "pack_file": "de-1.0.0.pack.gz"}]
        }), encoding='utf-8')

        # Missing attribution
        source_json = json.dumps({"license_id": "CC0-1.0"})
        db = create_mock_db([("lex1", "Haus", "noun", "ltr", "de", source_json)])
        pack_data = create_mock_pack(db)
        (self.packs_dir / "de-1.0.0.pack.gz").write_bytes(pack_data)

        res = self.run_exporter()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Missing attribution", res.stderr)

        # Unsupported license
        source_json = json.dumps({"license_id": "Proprietary", "attribution": "Me"})
        db = create_mock_db([("lex1", "Haus", "noun", "ltr", "de", source_json)])
        pack_data = create_mock_pack(db)
        (self.packs_dir / "de-1.0.0.pack.gz").write_bytes(pack_data)

        res = self.run_exporter()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Unsupported license", res.stderr)

    def test_wrong_hashes(self):
        self.manifest_path.write_text(json.dumps({
            "intellectual_property_status": "PUBLIC_DOMAIN_ZERO_COPYRIGHT",
            "packs": [{"id": "de", "version": "1.0.0", "pack_file": "de-1.0.0.pack.gz", "sha256": "badhash"}]
        }), encoding='utf-8')

        db = create_mock_db([])
        pack_data = create_mock_pack(db)
        (self.packs_dir / "de-1.0.0.pack.gz").write_bytes(pack_data)

        res = self.run_exporter()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Pack hash mismatch", res.stderr)

    def test_path_traversal(self):
        self.manifest_path.write_text(json.dumps({
            "intellectual_property_status": "PUBLIC_DOMAIN_ZERO_COPYRIGHT",
            "packs": [{"id": "de", "version": "1.0.0", "pack_file": "de-1.0.0.pack.gz"}]
        }), encoding='utf-8')

        db = create_mock_db([])
        pack_data = create_mock_pack(db)
        (self.packs_dir / "de-1.0.0.pack.gz").write_bytes(pack_data)

        res = self.run_exporter(destination=self.root / '..out.zip')
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("path traversal", res.stderr.lower() + res.stdout.lower())

    def test_duplicate_entries(self):
        self.manifest_path.write_text(json.dumps({
            "intellectual_property_status": "PUBLIC_DOMAIN_ZERO_COPYRIGHT",
            "packs": [{"id": "de", "version": "1.0.0", "pack_file": "de-1.0.0.pack.gz"}]
        }), encoding='utf-8')

        source_json = json.dumps({"license_id": "CC0-1.0", "attribution": "Me"})
        # Duplicate lexicon IDs
        db = create_mock_db([
            ("lex1", "Haus", "noun", "ltr", "de", source_json),
            ("lex1", "Haus", "noun", "ltr", "de", source_json)
        ])
        pack_data = create_mock_pack(db)
        (self.packs_dir / "de-1.0.0.pack.gz").write_bytes(pack_data)

        res = self.run_exporter()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Duplicate entry found in lexicon", res.stderr)

    def test_reversed_pairs(self):
        self.manifest_path.write_text(json.dumps({
            "intellectual_property_status": "PUBLIC_DOMAIN_ZERO_COPYRIGHT",
            "packs": [{"id": "de", "version": "1.0.0", "pack_file": "de-1.0.0.pack.gz"}]
        }), encoding='utf-8')

        source_json = json.dumps({"license_id": "CC0-1.0", "attribution": "Me", "direction": "en_to_de"})
        db = create_mock_db(
            [("lex1", "Haus", "noun", "ltr", "de", source_json)],
            [("trans1", "sense_de", "sense_en", "en", "house", source_json)]
        )
        pack_data = create_mock_pack(db)
        (self.packs_dir / "de-1.0.0.pack.gz").write_bytes(pack_data)

        res = self.run_exporter()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Reversed pairs found in translations", res.stderr)

    def test_deterministic_output(self):
        self.manifest_path.write_text(json.dumps({
            "intellectual_property_status": "PUBLIC_DOMAIN_ZERO_COPYRIGHT",
            "packs": [{"id": "de", "version": "1.0.0", "pack_file": "de-1.0.0.pack.gz"}]
        }), encoding='utf-8')

        source_json = json.dumps({"license_id": "CC0-1.0", "attribution": "Me"})
        db = create_mock_db([("lex1", "Haus", "noun", "ltr", "de", source_json)])
        pack_data = create_mock_pack(db)
        (self.packs_dir / "de-1.0.0.pack.gz").write_bytes(pack_data)

        res1 = self.run_exporter(destination=self.root / 'out1.zip')
        self.assertEqual(res1.returncode, 0, res1.stderr)

        res2 = self.run_exporter(destination=self.root / 'out2.zip')
        self.assertEqual(res2.returncode, 0, res2.stderr)

        zip1_bytes = (self.root / 'out1.zip').read_bytes()
        zip2_bytes = (self.root / 'out2.zip').read_bytes()

        self.assertEqual(zip1_bytes, zip2_bytes)

        # Verify it is a valid zip and contains lexical
        with zipfile.ZipFile(self.root / 'out1.zip', 'r') as z:
            self.assertIn("de_lexical.jsonl", z.namelist())
            content = z.read("de_lexical.jsonl").decode('utf-8')
            self.assertIn("Haus", content)

if __name__ == '__main__':
    unittest.main()
