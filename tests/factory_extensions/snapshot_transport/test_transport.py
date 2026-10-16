"""Synthetic-only tests: no network, source dispatch, pack output or release."""
import bz2
import gzip
import hashlib
import json
import lzma
import tempfile
import unittest
from pathlib import Path
from tools.factory_extensions.snapshot_transport import transport as t


def sha(data):
    return hashlib.sha256(data).hexdigest()


class FakeResponse:
    def __init__(self, data, status=200, headers=None):
        self.data, self.status, self.pos = data, status, 0
        self.headers = headers if headers is not None else [
            ("Content-Length", str(len(data)))]

    def getheaders(self):
        return self.headers

    def read(self, n):
        chunk = self.data[self.pos:self.pos + n]
        self.pos += len(chunk)
        return chunk


class FakeConnection:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def request(self, method, path, headers):
        self.requests.append((method, path, headers))

    def getresponse(self):
        return self.response

    def close(self):
        pass


class Tests(unittest.TestCase):
    def setUp(self):
        self.context = tempfile.TemporaryDirectory()
        self.addCleanup(self.context.cleanup)
        self.root = Path(self.context.name)
        self.repo = self.root / "repo"
        (self.repo / "catalog").mkdir(parents=True)
        (self.repo / "legal/ledger").mkdir(parents=True)
        (self.repo / "proof").write_bytes(b"fixture proof")
        registry = {"schema_version": "1.0.0",
                    "languages": [{"id": "de", "default_script": "Latn"},
                                  {"id": "ar", "default_script": "Arab"}]}
        (self.repo / "catalog/language_registry.v1.json").write_text(json.dumps(registry))
        self.payload = (b'{"lang_code":"de","word":"Brot"}\n'
                        + '{"lang_code":"de","word":"Äpfel 😊"}\n'.encode("utf-8"))
        self.url = "https://datasets.example.org/frozen.jsonl"
        self.entry = {
            "source_id": "synthetic", "kind": "dictionary",
            "status": "APPROVED_FOR_REDISTRIBUTION", "dataset_version": "v1",
            "publisher": "synthetic test", "origin_url": self.url,
            "retrieval": {"identity": "v1", "url": self.url, "date": "2026-10-13",
                          "artifact_path": "missing/frozen.jsonl",
                          "sha256": sha(self.payload)},
            "license": {"id": "CC0-1.0",
                        "evidence_url": "https://datasets.example.org/legal/proof",
                        "evidence_path": "proof", "evidence_sha256": sha(b"fixture proof")},
            "review": {"reviewer": "synthetic test",
                       "decision_url": "https://datasets.example.org/approval"},
            "alterations": ["none"]}
        self.save()
        self.store = self.root / "durable-mount"
        self.store.mkdir()

    def save(self):
        ledger = {"schema_version": "1.0.0", "sources": [self.entry]}
        (self.repo / "legal/ledger/sources.json").write_text(json.dumps(ledger))

    def approved(self, data=None):
        raw = self.payload if data is None else data
        self.entry["retrieval"]["sha256"] = sha(raw)
        self.save()
        return t.approved_source(self.repo, "synthetic", "v1", "de", self.url,
                                 sha(raw), len(raw), {"datasets.example.org"})

    def test_no_source_is_never_eligible(self):
        (self.repo / "legal/ledger/sources.json").write_text(
            '{"schema_version":"1.0.0","sources":[]}')
        with self.assertRaises(t.Blocked):
            t.approved_source(self.repo, "synthetic", "v1", "de", self.url,
                              sha(self.payload), len(self.payload), {"datasets.example.org"})

    def test_exact_approval_and_evidence(self):
        a = self.approved()
        self.assertEqual(a.sha256, sha(self.payload))
        cases = [
            ("wrong", "v1", "de", self.url, sha(self.payload)),
            ("synthetic", "v2", "de", self.url, sha(self.payload)),
            ("synthetic", "v1", "fr", self.url, sha(self.payload)),
            ("synthetic", "v1", "de", self.url + "?new=1", sha(self.payload)),
            ("synthetic", "v1", "de", self.url, "0" * 64)]
        for sid, ver, lang, url, digest in cases:
            with self.assertRaises(t.Blocked):
                t.approved_source(self.repo, sid, ver, lang, url, digest,
                                  len(self.payload), {"datasets.example.org"})
        self.entry["status"] = "REVIEW_REQUIRED"
        self.save()
        with self.assertRaises(t.Blocked):
            t.approved_source(self.repo, "synthetic", "v1", "de", self.url,
                              sha(self.payload), len(self.payload), {"datasets.example.org"})
        self.entry["status"] = "APPROVED_FOR_REDISTRIBUTION"
        self.entry["license"]["evidence_sha256"] = "0" * 64
        self.save()
        with self.assertRaises(t.Blocked):
            t.approved_source(self.repo, "synthetic", "v1", "de", self.url,
                              sha(self.payload), len(self.payload), {"datasets.example.org"})

    def test_dns_https_ssrf_redirect_and_credential_rejection(self):
        for url in ("http://datasets.example.org/x", "https://127.0.0.1/x",
                    "https://datasets.example.org.evil.test/x",
                    "https://user@datasets.example.org/x",
                    "https://datasets.example.org:8080/x",
                    "https://datasets.example.org./x",
                    "https://datasets.example.org/x?token=secret"):
            with self.subTest(url=url), self.assertRaises(t.Blocked):
                t.reviewed_target(url, {"datasets.example.org"})
        for ips in (["127.0.0.1"], ["8.8.8.8", "10.1.2.3"], []):
            def fake(*args, **kwargs):
                return [(2, 1, 0, "", (ip, 443)) for ip in ips]
            with self.assertRaises(t.Blocked):
                t.public_ips("datasets.example.org", fake)
        source = self.approved()
        redirect = FakeConnection(FakeResponse(b"", 302, [("Location", "https://evil.test")]))
        with self.assertRaises(t.Blocked):
            t.download(source, self.root / "download", connection_factory=lambda _: redirect)
        self.assertFalse((self.root / "download").exists())

    def test_range_resume_exact_sha_and_stale_identity(self):
        src = self.approved()
        part = self.root / "download.part"
        part.write_bytes(self.payload[:8])
        stamp = self.root / "download.identity.json"
        stamp.write_bytes(t.canonical({"identity": src.identity, "size": src.size}))
        response = FakeResponse(self.payload[8:], 206, [
            ("Content-Length", str(len(self.payload) - 8)),
            ("Content-Range", f"bytes 8-{len(self.payload)-1}/{len(self.payload)}")])
        conn = FakeConnection(response)
        report = t.download(src, self.root / "download", connection_factory=lambda _: conn)
        self.assertEqual(report["downloaded_bytes"], len(self.payload) - 8)
        self.assertEqual(conn.requests[0][2]["Range"], f"bytes=8-{len(self.payload)-1}")
        self.assertEqual((self.root / "download").read_bytes(), self.payload)
        self.assertEqual(t.download(src, self.root / "download")["downloaded_bytes"], 0)
        (self.root / "download").unlink()
        stamp.write_bytes(b"foreign")
        with self.assertRaises(t.Blocked):
            t.download(src, self.root / "download", connection_factory=lambda _: conn)

    def test_replay_corruption_and_determinism(self):
        src = self.approved()
        f = self.root / "source"
        f.write_bytes(self.payload)
        with self.assertRaisesRegex(RuntimeError, "termination"):
            t.stage(src, f, self.store, shard_rows=1, fault_after_shards=1)
        receipt = t.stage(src, f, self.store, shard_rows=1)
        self.assertEqual([receipt["shards"], receipt["replayed_shards"],
                          receipt["new_shards"]], [2, 1, 1])
        manifest_path = self.store / "manifests" / (src.identity + ".json")
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest["input_rows"], 2)
        self.assertEqual(manifest["status"], "STAGED_ONLY")
        self.assertFalse(manifest["publication_approved"])
        self.assertEqual(receipt["manifest_sha256"], sha(manifest_path.read_bytes()))
        shard = self.store / "shards" / (manifest["partitions"][1]["sha256"] + ".jsonl")
        self.assertIn("😊", shard.read_text())
        other = t.stage(src, f, self.store, shard_rows=1)
        self.assertEqual([other["replayed_shards"], other["new_shards"]], [2, 0])
        self.assertEqual(other["manifest_sha256"], receipt["manifest_sha256"])
        shard.write_bytes(b"corruption")
        with self.assertRaises(t.Blocked):
            t.stage(src, f, self.store, shard_rows=1)

    def test_bounded_shards_compressions_and_deduplicated_payloads(self):
        for fmt, compressor in [
            ("jsonl.gz", lambda b: gzip.compress(b, mtime=0)),
            ("jsonl.bz2", bz2.compress),
            ("jsonl.xz", lzma.compress)]:
            with self.subTest(fmt=fmt):
                compressed = compressor(self.payload)
                src = self.approved(compressed)
                path = self.root / "compressed"
                path.write_bytes(compressed)
                self.assertEqual(t.stage(src, path, self.store, fmt=fmt,
                                         shard_rows=1)["input_rows"], 2)
        self.assertEqual(len(list((self.store / "manifests").glob("*.json"))), 3)
        self.assertEqual(len(list((self.store / "shards").glob("*.jsonl"))), 2)

    def test_wrong_language_invalid_utf8_duplicate_keys_and_expansion_limit(self):
        wrong = [b'{"lang_code":"ar"}\n',
                 b'{"lang_code":"de","x":\xff}\n',
                 b'{"lang_code":"de","lang_code":"de"}\n',
                 b'{"lang_code":"de"}',
                 b'{"lang_code":"de"}\n' * 3]
        for index, data in enumerate(wrong):
            with self.subTest(index=index):
                src = self.approved(data)
                f = self.root / "invalid"
                f.write_bytes(data)
                kwargs = {"max_expanded": len(data)-1} if index == 4 else {}
                with self.assertRaises(t.Blocked):
                    t.stage(src, f, self.store, **kwargs)
        src = self.approved()
        (self.root / "invalid").write_bytes(self.payload + b"extra")
        with self.assertRaises(t.Blocked):
            t.stage(src, self.root / "invalid", self.store)

    def test_storage_absent_or_modified_partition_strategy_rejected(self):
        source = self.approved()
        f = self.root / "source"
        f.write_bytes(self.payload)
        with self.assertRaises(t.Blocked):
            t.stage(source, f, self.root / "not-mounted")
        with self.assertRaises(t.Blocked):
            t.stage(source, f, self.store, shard_rows=10001)
        t.stage(source, f, self.store, shard_rows=1)
        with self.assertRaises(t.Blocked):
            t.stage(source, f, self.store, shard_rows=2)


if __name__ == "__main__":
    unittest.main()
