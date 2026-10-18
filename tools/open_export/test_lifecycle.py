"""Synthetic-only security regression suite; fixture approvals are NOT legal evidence."""
import hashlib
import base64
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from community.contributions.ingest import ingest, members, unique_json, quarantine_submission
from community.review.state_machine import ReviewStateMachine, sign
from community.review.cli import main as review_cli_main
from tools.open_export.exporter import CommunityExporter, ExportError, MAX_RELEASE_BYTES


def digest(data):
    return hashlib.sha256(data).hexdigest()


class SecurityRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src = self.root / "contributions"
        self.src.mkdir()
        self.review_root = self.root / "reviews"
        self.out = self.root / "out"
        self.auth = {"validator": b"v" * 32, "reviewer": b"r" * 32}
        self.machine = ReviewStateMachine(self.review_root, self.src,
                                          validator_keys={"validator": self.auth["validator"]},
                                          reviewer_keys={"reviewer": self.auth["reviewer"]})
        self.meta = {"source_id": "src-test", "language": "de", "sense_id": "sense-test",
                     "license_id": "CC0-1.0", "dataset_version": "1.0", "publisher": "Fixture publisher",
                     "origin_url": "https://example.org/data", "record_locator": "row-1",
                     "source_artifact_sha256": "a" * 64, "fixture_only": False,
                     "rights_status": "APPROVED_FOR_REDISTRIBUTION"}
        self.ledger = {"schema_version": "1.0.0", "sources": [{"source_id": "src-test",
                       "status": "APPROVED_FOR_REDISTRIBUTION", "dataset_version": "1.0",
                       "publisher": "Fixture publisher", "origin_url": "https://example.org/data",
                       "kind": "dictionary", "retrieval": {"sha256": "a" * 64},
                       "license": {"id": "CC0-1.0", "evidence_url": "https://example.org/rights"}}]}
        ledgerpath = self.root / "legal/ledger"
        ledgerpath.mkdir(parents=True)
        (ledgerpath / "sources.json").write_text(json.dumps(self.ledger))
        catalog = self.root / "catalog"
        catalog.mkdir()
        (catalog / "content_readiness.v1.json").write_text(json.dumps({"schema_version": "1.0.0", "states": {"de": "unverified"}}))

    def stage(self, sid="item1", content=b"source-backed bytes"):
        filename = sid + ".bin"
        path = self.src / filename
        path.write_bytes(content)
        sha = digest(content)
        self.machine.submit(sid, sha, self.meta, path)
        return filename, sha

    def certify(self, sid="item1"):
        self.machine.start_validation(sid)
        data = self.machine._read(sid)
        token = sign(self.auth["validator"], self.machine.payload(data, "VALIDATE", "validator"))
        self.machine.complete_validation(sid, "validator", token)
        data = self.machine._read(sid)
        token = sign(self.auth["reviewer"], self.machine.payload(data, "APPROVE", "reviewer"))
        self.machine.review(sid, "reviewer", True, token)
        return self.machine.mark_published_eligible(sid)

    def manifest(self, filename, sha, sid="item1"):
        (self.src / "manifest.json").write_text(json.dumps({"items": [{
            "id": sid, "type": "lexical", "filename": filename, "sha256": sha,
            "submission_id": sid, "source_id": "src-test", "license": "CC0-1.0",
            "source_version": "1.0"}]}))

    def export(self):
        # A simulated admission gate never replaces real verified rights evidence.
        with patch.dict(sys.modules, {"legal.ledger.admission": SimpleNamespace(evaluate=lambda *_: [])}):
            return CommunityExporter(self.src, self.out, self.machine, repository_root=self.root).run()

    def test_reject_path_traversal_and_symlink_in_review(self):
        for sid in ("../outside", "a/b", "..", "evil.json/../../"):
            with self.assertRaises(ValueError):
                self.machine.submit(sid, "0" * 64, self.meta, self.src / "whatever")
        outside = self.root / "outside"
        outside.write_bytes(b"hi")
        (self.src / "link.bin").symlink_to(outside)
        with self.assertRaises(ValueError):
            self.machine.submit("item1", digest(b"hi"), self.meta, self.src / "link.bin")

    def test_approval_requires_independent_keys_and_hash_binding(self):
        self.stage()
        self.machine.start_validation("item1")
        with self.assertRaises(PermissionError):
            self.machine.complete_validation("item1", "validator", "claimed-passed")
        data = self.machine._read("item1")
        vtoken = sign(self.auth["validator"], self.machine.payload(data, "VALIDATE", "validator"))
        self.machine.complete_validation("item1", "validator", vtoken)
        with self.assertRaises(PermissionError):
            self.machine.review("item1", "anonymous", True, vtoken)
        data = self.machine._read("item1")
        rtoken = sign(self.auth["reviewer"], self.machine.payload(data, "APPROVE", "reviewer"))
        self.machine.review("item1", "reviewer", True, rtoken)
        (self.src / "item1.bin").write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            self.machine.mark_published_eligible("item1")

    def test_corrections_invalidate_prior_approval(self):
        self.stage()
        self.certify()
        self.stage(content=b"new revision")
        with self.assertRaises(ValueError):
            self.machine.verify_handoff("item1")
        self.assertEqual(self.machine._read("item1")["state"], "SUBMITTED")

    def test_concurrent_same_submission_idempotent(self):
        filename, sha = self.stage()
        def same(_):
            return self.machine.submit("item1", sha, self.meta, self.src / filename)["revision"]
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(list(pool.map(same, range(8))), [1] * 8)

    def test_archive_traversal_tar_symlinks_zip_bombs(self):
        with io.BytesIO() as b:
            with zipfile.ZipFile(b, "w") as z:
                z.writestr("../escape.json", "{}")
            with self.assertRaises(ValueError):
                list(members(b.getvalue(), "bad.zip"))
        with io.BytesIO() as b:
            with tarfile.open(fileobj=b, mode="w:gz") as t:
                info = tarfile.TarInfo("link.json")
                info.type = tarfile.SYMTYPE
                info.linkname = "../../escape"
                t.addfile(info)
            with self.assertRaises(ValueError):
                list(members(b.getvalue(), "bad.tar.gz"))
        import gzip
        with self.assertRaises(ValueError):
            list(members(gzip.compress(b"x" * (16 * 1024 * 1024 + 1)), "bomb.json.gz"))

    def test_intake_duplicate_keys_and_fixture_rejection(self):
        with self.assertRaises(ValueError):
            unique_json(b'{"a":1,"a":2}')
        entry = {"contract_version": "1.0.0", "document_id": "doc-1", "lexemes": [{"source": {
            "source_id": "src-test", "license_id": "CC0-1.0", "fixture_only": True,
            "dataset_version": "1", "record_locator": "1", "publisher": "demo",
            "origin_url": "https://example.org", "artifact_sha256": "a" * 64}}],
                 "senses": [], "translations": [], "examples": [], "relations": []}
        content = self.root / "fixture.json"
        content.write_text(json.dumps(entry))
        registry = self.root / "registry.json"
        registry.write_text('{"states":{"de":"unverified"}}')
        with self.assertRaisesRegex(ValueError, "provenance"):
            ingest(content, self.root / "stage", registry_path=registry,
                   validator=lambda *_args, **_kwargs: None, licenses={"CC0-1.0"})
        entry["lexemes"][0]["source"]["fixture_only"] = False
        content.write_text(json.dumps(entry))
        receipt = ingest(content, self.root / "stage", registry_path=registry,
                         validator=lambda *_args, **_kwargs: None, licenses={"CC0-1.0"})
        self.assertEqual(receipt["state"], "STAGED_REVIEW_REQUIRED")
        self.assertFalse(receipt["rights_approved"])
        self.assertEqual(receipt, ingest(content, self.root / "stage", registry_path=registry,
                                         validator=lambda *_args, **_kwargs: None, licenses={"CC0-1.0"}))

    def test_export_reject_unreviewed_tampering_and_ledger_mismatch(self):
        name, sha = self.stage()
        self.manifest(name, sha)
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.export()
        self.certify()
        self.ledger["sources"][0]["status"] = "UNVERIFIED_RIGHTS"
        (self.root / "legal/ledger/sources.json").write_text(json.dumps(self.ledger))
        with self.assertRaisesRegex(ValueError, "not approved"):
            self.export()
        self.ledger["sources"][0]["status"] = "APPROVED_FOR_REDISTRIBUTION"
        (self.root / "legal/ledger/sources.json").write_text(json.dumps(self.ledger))
        (self.src / name).write_bytes(b"different content")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.export()

    def test_deterministic_export_and_failed_run_preserves_last_good(self):
        name, sha = self.stage()
        self.certify()
        self.manifest(name, sha)
        first = self.export()
        second = self.export()
        self.assertEqual(first, second)
        with zipfile.ZipFile(self.out / "releases" / first["release"]) as z:
            self.assertEqual(z.namelist(), ["data/item1.bin", "ATTRIBUTION.json"])
        (self.src / "manifest.json").write_text('{"items":[{"id":"../../oops"}]}')
        with self.assertRaises(ValueError):
            self.export()
        self.assertEqual(json.loads((self.out / "CURRENT.json").read_text()), first)

    def test_export_unsafe_symlinks_and_bounded_size(self):
        name, sha = self.stage()
        self.certify()
        self.manifest(name, sha)
        (self.src / name).unlink()
        (self.src / name).symlink_to(self.root / "legal/ledger/sources.json")
        with self.assertRaises(ValueError):
            self.export()


    def test_too_many_tar_members_are_rejected(self):
        with io.BytesIO() as b:
            with tarfile.open(fileobj=b, mode="w:gz") as archive:
                for i in range(129):
                    raw = b"{}"
                    info = tarfile.TarInfo("entry%03d.json" % i)
                    info.size = len(raw)
                    archive.addfile(info, io.BytesIO(raw))
            with self.assertRaisesRegex(ValueError, "member count"):
                list(members(b.getvalue(), "too-many.tar.gz"))

    def test_cached_export_rejects_compressed_zip_bomb(self):
        name, sha = self.stage()
        self.certify()
        self.manifest(name, sha)
        output = self.export()
        release = self.out / "releases" / output["release"]
        with zipfile.ZipFile(release, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("data/item1.bin", b"x" * (8 * 1024 * 1024 + 1))
            archive.writestr("ATTRIBUTION.json", b"{}")
        with self.assertRaisesRegex(ValueError, "untrusted cached"):
            self.export()
        self.assertEqual(json.loads((self.out / "CURRENT.json").read_text()), output)

    def test_cached_export_rejects_oversized_padded_zip(self):
        name, sha = self.stage()
        self.certify()
        self.manifest(name, sha)
        receipt = self.export()
        release = self.out / "releases" / receipt["release"]
        pointer = (self.out / "CURRENT.json").read_bytes()
        with zipfile.ZipFile(release) as archive:
            entries = [(name, archive.read(name)) for name in archive.namelist()]
        # A sparse prefix keeps the fixture small in memory; the ZIP itself
        # remains well-formed and its members/hash metadata are unchanged.
        with release.open("wb") as stream:
            stream.truncate(MAX_RELEASE_BYTES + 1)
        with zipfile.ZipFile(release, "a", compression=zipfile.ZIP_STORED) as archive:
            for filename, content in entries:
                archive.writestr(filename, content, compress_type=zipfile.ZIP_STORED)
        self.assertGreater(release.stat().st_size, MAX_RELEASE_BYTES)
        with self.assertRaisesRegex(ExportError, "archive byte limit"):
            self.export()
        self.assertEqual((self.out / "CURRENT.json").read_bytes(), pointer)

    def test_manifest_self_approval_cannot_replace_signed_handoff(self):
        name, sha = self.stage()
        self.manifest(name, sha)
        manifest_path = self.src / "manifest.json"
        content = json.loads(manifest_path.read_text())
        content["items"][0]["evidence"] = "approved_by_admin"
        content["items"][0]["rights_status"] = "APPROVED_FOR_REDISTRIBUTION"
        manifest_path.write_text(json.dumps(content))
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.export()

    def test_ledger_artifact_and_kind_must_match(self):
        name, sha = self.stage()
        self.certify()
        self.manifest(name, sha)
        self.ledger["sources"][0]["retrieval"]["sha256"] = "b" * 64
        (self.root / "legal/ledger/sources.json").write_text(json.dumps(self.ledger))
        with self.assertRaisesRegex(ValueError, "ledger provenance mismatch"):
            self.export()
        self.ledger["sources"][0]["retrieval"]["sha256"] = "a" * 64
        self.ledger["sources"][0]["kind"] = "vector_art"
        (self.root / "legal/ledger/sources.json").write_text(json.dumps(self.ledger))
        with self.assertRaisesRegex(ValueError, "source kind"):
            self.export()


    def test_review_handoff_restart_recovery(self):
        self.stage()
        self.certify()
        path = self.machine.handoff_dir / "item1_handoff.json"
        before = len(self.machine._read("item1")["history"])
        path.unlink()
        self.machine.mark_published_eligible("item1")
        self.assertEqual(len(self.machine._read("item1")["history"]), before)
        self.assertEqual(self.machine.verify_handoff("item1")["state"], "PUBLISHED_ELIGIBLE")

    def test_export_blocks_unknown_languages_and_oversized_attribution(self):
        self.meta["language"] = "xx"
        name, sha = self.stage()
        self.certify()
        self.manifest(name, sha)
        with self.assertRaisesRegex(ValueError, "unregistered language"):
            self.export()
        self.machine.submit("item1", sha, {**self.meta, "language": "de", "publisher": "P" * 70000},
                            self.src / name)
        self.ledger["sources"][0]["publisher"] = "P" * 70000
        (self.root / "legal/ledger/sources.json").write_text(json.dumps(self.ledger))
        self.machine.start_validation("item1")
        data = self.machine._read("item1")
        self.machine.complete_validation("item1", "validator",
            sign(self.auth["validator"], self.machine.payload(data, "VALIDATE", "validator")))
        data = self.machine._read("item1")
        self.machine.review("item1", "reviewer", True,
            sign(self.auth["reviewer"], self.machine.payload(data, "APPROVE", "reviewer")))
        self.machine.mark_published_eligible("item1")
        with self.assertRaisesRegex(ValueError, "attribution metadata"):
            self.export()


    def test_quarantine_preserves_rejected_bytes_and_reason(self):
        rejected = self.root / "malformed.json"
        rejected.write_bytes(b"{broken")
        receipt = quarantine_submission(rejected, self.root / "isolation", "Invalid JSON")
        self.assertEqual(receipt["state"], "QUARANTINED")
        self.assertFalse(receipt["rights_approved"])
        isolated = self.root / "isolation/quarantined"
        self.assertEqual((isolated / (receipt["sha256"] + ".bin")).read_bytes(), b"{broken")
        self.assertIn("Invalid JSON", (isolated / (receipt["sha256"] + ".json")).read_text())
        self.assertEqual(rejected.read_bytes(), b"{broken")
        self.assertEqual(quarantine_submission(rejected, self.root / "isolation", "Invalid JSON"), receipt)


    def test_operator_cli_requires_signed_decisions(self):
        keyfile = self.root / "operator.json"
        keyfile.write_text(json.dumps({
            "validators": {"validator": base64.b64encode(self.auth["validator"]).decode()},
            "reviewers": {"reviewer": base64.b64encode(self.auth["reviewer"]).decode()}
        }))
        keyfile.chmod(0o600)
        data = b"independent operator-submitted bytes"
        art = self.src / "operator.bin"
        art.write_bytes(data)
        metadata = self.root / "claimed.json"
        metadata.write_text(json.dumps(self.meta))
        common = ["--storage", str(self.review_root), "--artifacts", str(self.src),
                  "--operator-keys", str(keyfile)]
        self.assertEqual(review_cli_main(common + ["submit", "--id", "operator1", "--sha256",
                         digest(data), "--metadata", str(metadata), "--artifact", str(art)]), 0)
        self.assertEqual(review_cli_main(common + ["start", "--id", "operator1"]), 0)
        self.assertEqual(review_cli_main(common + ["validate", "--id", "operator1",
                         "--actor", "validator", "--token", "self-declared-pass"]), 1)
        state = self.machine._read("operator1")
        validated = sign(self.auth["validator"], self.machine.payload(state, "VALIDATE", "validator"))
        self.assertEqual(review_cli_main(common + ["validate", "--id", "operator1",
                         "--actor", "validator", "--token", validated]), 0)
        state = self.machine._read("operator1")
        approved = sign(self.auth["reviewer"], self.machine.payload(state, "APPROVE", "reviewer"))
        self.assertEqual(review_cli_main(common + ["approve", "--id", "operator1",
                         "--actor", "reviewer", "--token", approved]), 0)
        self.assertEqual(review_cli_main(common + ["eligible", "--id", "operator1"]), 0)
        self.assertEqual(self.machine.verify_handoff("operator1")["state"], "PUBLISHED_ELIGIBLE")


if __name__ == "__main__":
    unittest.main()
