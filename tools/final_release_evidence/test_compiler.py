import unittest
import json
import tempfile
import os
import gzip
from pathlib import Path

from compiler import run_compiler, get_sha256

class TestFinalReleaseEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)

        self.registry_path = self.root / "registry.json"
        self.manifest_path = self.root / "manifest.json"
        self.packs_dir = self.root / "packs"
        self.packs_dir.mkdir()
        self.output_path = self.root / "evidence.json"

        # Setup basic registry
        self.registry_data = {
            "schema_version": "1.0.0",
            "languages": [{"id": f"lang{i}"} for i in range(100)]
        }
        self.write_json(self.registry_path, self.registry_data)

        self.manifest_data = {
            "schemaVersion": "2.0.0",
            "languages": []
        }
        self.write_json(self.manifest_path, self.manifest_data)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def write_json(self, path, data):
        with open(path, "w") as f:
            json.dump(data, f)

    def write_pack(self, name, data_dict=None):
        path = self.packs_dir / name
        if data_dict is None:
            data_dict = {"header": {"version": "1.0", "license": "CC0", "levels": ["A1"]}, "domains": [{"icon_vector": "test"}]}
        content = json.dumps(data_dict).encode("utf-8")
        with gzip.open(path, "wb") as f:
            f.write(content)
        return path

    def test_all_100_ids(self):
        # We need to make sure 100 ids have something
        for i in range(100):
            lang_id = f"lang{i}"
            if i < 15: # metadataOnly (missing from manifest)
                pass
            elif i < 30: # metadataOnly (missing pack_file in manifest)
                self.manifest_data["languages"].append({"code": lang_id})
            elif i < 45: # sourceMissing
                self.manifest_data["languages"].append({"code": lang_id, "pack_file": f"{lang_id}.pack.gz"})
            elif i < 60: # invalidPack (size mismatch)
                pack_path = self.write_pack(f"{lang_id}.pack.gz")
                self.manifest_data["languages"].append({
                    "code": lang_id, "pack_file": f"{lang_id}.pack.gz",
                    "size_bytes": 9999, "sha256": "fake"
                })
            elif i < 75: # licenseBlocked
                pack_path = self.write_pack(f"{lang_id}.pack.gz")
                self.manifest_data["languages"].append({
                    "code": lang_id, "pack_file": f"{lang_id}.pack.gz",
                    "size_bytes": pack_path.stat().st_size, "sha256": get_sha256(pack_path),
                    "legacy_asset_status": "UNVERIFIED_LEGACY"
                })
            else: # releaseReady
                pack_path = self.write_pack(f"{lang_id}.pack.gz")
                self.manifest_data["languages"].append({
                    "code": lang_id, "pack_file": f"{lang_id}.pack.gz",
                    "size_bytes": pack_path.stat().st_size, "sha256": get_sha256(pack_path),
                    "pack_verified": True, "production_ready": True
                })

        self.write_json(self.manifest_path, self.manifest_data)
        result = run_compiler(self.registry_path, self.manifest_path, self.packs_dir, self.output_path)

        evidence = result["evidence"]
        self.assertEqual(len(evidence), 100)

        for i in range(100):
            lang_id = f"lang{i}"
            if i < 30:
                self.assertEqual(evidence[lang_id]["status"], "metadataOnly")
            elif i < 45:
                self.assertEqual(evidence[lang_id]["status"], "sourceMissing")
            elif i < 60:
                self.assertEqual(evidence[lang_id]["status"], "invalidPack")
            elif i < 75:
                self.assertEqual(evidence[lang_id]["status"], "licenseBlocked")
            else:
                self.assertEqual(evidence[lang_id]["status"], "releaseReady")
                self.assertEqual(evidence[lang_id]["cefr_evidence"], ["A1"])
                self.assertEqual(evidence[lang_id]["source_licenses"], ["CC0"])

    def test_fail_closed_prev_evidence(self):
        # Write valid evidence first
        valid_evidence = {"schema_version": "1.0.0", "evidence": {}}
        self.write_json(self.output_path, valid_evidence)

        # Break json
        with open(self.registry_path, "w") as f:
            f.write("invalid json")

        with self.assertRaises(json.decoder.JSONDecodeError):
            run_compiler(self.registry_path, self.manifest_path, self.packs_dir, self.output_path)

        # Old output should still exist
        with open(self.output_path, "r") as f:
            self.assertEqual(json.load(f), valid_evidence)

if __name__ == "__main__":
    unittest.main()
