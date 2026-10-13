"""Synthetic-only negative and positive fixtures: never production vocabulary."""
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[3] / "tools/factory_extensions/unimorph_tsv_probe/probe.py"
spec = importlib.util.spec_from_file_location("unimorph_probe", MODULE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class UniMorphProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "fixture.tsv"

    def run_probe(self, data: bytes, first=1, last=1, sha=None):
        self.path.write_bytes(data)
        return probe.inspect(source=self.path,
                             expected_sha256=sha or hashlib.sha256(data).hexdigest(),
                             language="eng", first_line=first, last_line=last)

    def test_inspection_only_and_no_production_admission(self):
        r = self.run_probe(b"lemma\tform\tV;PST\n")
        self.assertEqual(r["candidate_rows"], 1)
        self.assertEqual(r["real_persisted_accepted"], 0)
        self.assertEqual(r["status"], "INSPECTION_ONLY_RIGHTS_NOT_GRANTED")

    def test_duplicate_count(self):
        r = self.run_probe(b"lemma\tform\tV;PST\nlemma\tform\tV;PST\n", last=2)
        self.assertEqual((r["candidate_rows"], r["duplicate_rows"]), (1, 1))

    def test_invalid_utf8_rejected(self):
        r = self.run_probe(b"lemma\t\xff\tV\n")
        self.assertEqual(r["rejection_reasons"], {"INVALID_UTF8": 1})

    def test_wrong_columns_rejected(self):
        r = self.run_probe(b"lemma\tform\n")
        self.assertEqual(r["rejection_reasons"], {"COLUMN_COUNT": 1})

    def test_unknown_lowercase_feature_rejected(self):
        r = self.run_probe(b"lemma\tform\tguess\n")
        self.assertEqual(r["rejection_reasons"], {"INVALID_TAG_SYNTAX": 1})

    def test_bidi_control_rejected(self):
        r = self.run_probe("lem\u202ema\tform\tN\n".encode())
        self.assertEqual(r["rejection_reasons"], {"INVALID_TEXT": 1})

    def test_numeric_feature_tag_is_not_rejected_by_syntax(self):
        r = self.run_probe(b"lemma\tform\tV;PST;1;SG\n")
        self.assertEqual(r["candidate_rows"], 1)

    def test_oversized_line_does_not_swallow_next_row(self):
        r = self.run_probe(b"x" * (probe.MAX_LINE_BYTES + 100) + b"\nlemma\tform\tV\n", last=2)
        self.assertEqual((r["rejected_rows"], r["candidate_rows"]), (1, 1))

    def test_crlf_supported(self):
        r = self.run_probe(b"lemma\tform\tV;PRS\r\n")
        self.assertEqual(r["candidate_rows"], 1)

    def test_truncated_partition_fails(self):
        with self.assertRaisesRegex(probe.ProbeError, "TRUNCATED_PARTITION"):
            self.run_probe(b"lemma\tform\tV\n", last=2)

    def test_wrong_sha_fails(self):
        with self.assertRaisesRegex(probe.ProbeError, "SOURCE_HASH_MISMATCH"):
            self.run_probe(b"lemma\tform\tV\n", sha="0" * 64)

    def test_invalid_partition_rejected(self):
        with self.assertRaisesRegex(probe.ProbeError, "INVALID_BOUNDED_PARTITION"):
            self.run_probe(b"lemma\tform\tV\n", last=10001)

    def test_oversized_line_rejected(self):
        r = self.run_probe(b"x" * (probe.MAX_LINE_BYTES + 1) + b"\n")
        self.assertEqual(r["rejection_reasons"], {"OVERSIZED_LINE": 1})

    def test_symlink_source_rejected(self):
        self.path.write_bytes(b"lemma\tform\tV\n")
        link = Path(self.tmp.name) / "link.tsv"
        link.symlink_to(self.path)
        with self.assertRaisesRegex(probe.ProbeError, "UNSAFE_OR_OVERSIZED_SOURCE"):
            probe.inspect(source=link, expected_sha256=hashlib.sha256(self.path.read_bytes()).hexdigest(),
                          language="eng", first_line=1, last_line=1)

    def test_deterministic_fingerprint(self):
        a = self.run_probe(b"lemma\tform\tV\n")
        b = self.run_probe(b"lemma\tform\tV\n")
        self.assertEqual(a["partition_fingerprint"], b["partition_fingerprint"])

    def test_invalid_language_rejected(self):
        data = b"lemma\tform\tV\n"
        self.path.write_bytes(data)
        with self.assertRaisesRegex(probe.ProbeError, "EXPLICIT_ISO639_3_LANGUAGE_REQUIRED"):
            probe.inspect(source=self.path, expected_sha256=hashlib.sha256(data).hexdigest(),
                          language="en", first_line=1, last_line=1)


if __name__ == "__main__":
    unittest.main()
