"""Original pinned Lexeme JSON -> review-only sense candidates, no network."""
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.gha_factory.admission import original_lexeme_candidates as c


class OriginalLexemeCandidatesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = c.strict_json((c.ROOT / c.FOLDER / "receipt.json").read_bytes())
        cls.candidates = c.strict_json((c.ROOT / c.FOLDER / "candidates.json").read_bytes())

    def test_rebuild_exact_original_sources_and_sha256(self):
        raw = (c.ROOT / c.FOLDER / "candidates.json").read_bytes()
        self.assertEqual(c.canonical(c.build(c.ROOT, self.receipt)), raw)
        self.assertEqual(c.digest(raw), self.receipt["candidate_sha256"])

    def test_actual_rows_forms_senses_and_priority_languages(self):
        data = c.build(c.ROOT, self.receipt)
        self.assertEqual((data["actual_rows"], data["lexeme_count"], data["form_count"]), (25, 3, 40))
        self.assertEqual({x["language"]: len(x["forms"]) for x in data["lexemes"]},
                         {"ar": 3, "de": 32, "en": 5})
        self.assertEqual({lang: sum(x["language"] == lang for x in data["candidates"])
                          for lang in ("de", "en", "ar")}, {"de": 5, "en": 19, "ar": 1})
        self.assertEqual(len({x["id"] for x in data["candidates"]}), 25)

    def test_no_fake_cefr_examples_translations_or_production(self):
        self.assertFalse(self.receipt["source_admission_approved"])
        self.assertFalse(self.receipt["production_ready"])
        self.assertTrue(self.receipt["original_lexeme_json_pinned"])
        self.assertEqual(self.receipt["topic_estimates"], 3)
        for row in self.candidates["candidates"]:
            self.assertEqual(row["level"], "UNKNOWN")
            self.assertEqual(row["review_status"], "REVIEW_REQUIRED")
            self.assertEqual(row["directed_translations"], [])
            self.assertEqual(row["examples"], [])
            self.assertIn(row["topic"], ("activities", "UNASSIGNED"))
            self.assertEqual(row["topic_status"],
                             "MAPPED_ESTIMATE" if row["topic"] == "activities" else "UNKNOWN")

    def test_fail_closed_false_approval_and_tampered_source(self):
        for field in ("production_ready", "source_admission_approved"):
            bad = dict(self.receipt, **{field: True})
            with self.assertRaises(ValueError):
                c.build(c.ROOT, bad)
        bad = copy.deepcopy(self.receipt)
        bad["source_files"][0]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            c.build(c.ROOT, bad)
        bad = copy.deepcopy(self.receipt)
        bad["source_files"][0]["revision"] += 1
        with self.assertRaises(ValueError):
            c.build(c.ROOT, bad)

    def test_nonfinite_json_exponents_are_rejected(self):
        # json.loads accepts 1e999 as float('inf') unless parse_float is guarded.
        for raw in (b'{"weight":1e999}', b'{"weight":-1e999}',
                    b'{"weight":NaN}', b'{"weight":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                c.strict_json(raw)
        self.assertEqual(c.strict_json(b'{"weight":1.25}'), {"weight": 1.25})

    def test_duplicate_source_lexeme_is_rejected(self):
        bad = copy.deepcopy(self.receipt)
        bad["source_files"].append(copy.deepcopy(bad["source_files"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate source lexeme"):
            c.build(c.ROOT, bad)

    def test_self_consistent_tampering_cannot_repin_source_or_license(self):
        # A changed source and a matching receipt-controlled digest are not
        # sufficient provenance: the independent main review pins must agree.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = [item["path"] for item in self.receipt["source_files"]]
            paths.append(self.receipt["license_evidence_path"])
            for name in paths:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(c.ROOT / name, target)

            bad = copy.deepcopy(self.receipt)
            source = bad["source_files"][0]
            target = root / source["path"]
            entity_json = c.strict_json(target.read_bytes())
            entity_json["entities"][source["lexeme_id"]]["lemmas"]["de"]["value"] = "forged-lemma"
            target.write_bytes(c.canonical(entity_json))
            source["sha256"] = c.digest(target.read_bytes())
            with self.assertRaisesRegex(ValueError, "source hash not independently pinned"):
                c.build(root, bad)

            # The original files are restored; now forge a matching receipt hash
            # for an altered rights notice that still contains the expected words.
            shutil.copyfile(c.ROOT / source["path"], target)
            bad = copy.deepcopy(self.receipt)
            notice = root / bad["license_evidence_path"]
            notice.write_bytes(notice.read_bytes() + b"\\nForged expanded rights scope\\n")
            bad["license_evidence_sha256"] = c.digest(notice.read_bytes())
            with self.assertRaisesRegex(ValueError, "license notice hash not independently pinned"):
                c.build(root, bad)

    def test_source_language_qid_is_not_receipt_controlled(self):
        # A self-consistent forged receipt/source must not relabel an English lexeme as German.
        bad = copy.deepcopy(self.receipt)
        bad["source_files"][0]["language_qid"] = "Q1860"
        with self.assertRaisesRegex(ValueError, "language QID"):
            c.build(c.ROOT, bad)

    def test_license_evidence_path_is_pinned_to_scoped_notice(self):
        # Matching arbitrary receipt-selected text is not independent license evidence.
        bad = copy.deepcopy(self.receipt)
        bad["license_evidence_path"] = bad["source_files"][0]["path"]
        with self.assertRaisesRegex(ValueError, "license evidence path"):
            c.build(c.ROOT, bad)

    def test_ranked_source_claims_never_infer_directed_translations(self):
        source = {"claims": {"P9970": [
            {"rank": "deprecated", "mainsnak": {"snaktype": "value",
             "datavalue": {"value": {"entity-type": "item", "id": "Q11"}}}},
            {"rank": "preferred", "mainsnak": {"snaktype": "novalue"}},
            {"rank": "normal", "mainsnak": {"snaktype": "value",
             "datavalue": {"value": {"entity-type": "item", "id": "Q22"}}}}
        ]}}
        self.assertEqual(c.claim_qids(source, "P9970"), [])
        self.assertEqual(self.receipt["directed_translations"], 0)

    def test_no_cross_batch_lexeme_duplication(self):
        from tools.gha_factory.admission import agent_harvest_candidates as a
        folders = [a.FOLDER] + [a.Path("legal/ledger/evidence/" + x)
                   for x in ("agent-harvest-20261024-batch2",
                             "agent-harvest-20261025-batch3",
                             "agent-harvest-20261025-batch4",
                             "agent-harvest-20261025-batch5",
                             "agent-harvest-20261025-batch6")]
        prior = set()
        for folder in folders:
            obj = json.loads((c.ROOT / folder / "candidates.json").read_text(encoding="utf-8"))
            prior.update((row["language"], row["lexeme_id"]) for row in obj["candidates"])
        self.assertFalse(prior.intersection(
            (row["language"], row["lexeme_id"]) for row in self.candidates["candidates"]))


if __name__ == "__main__":
    unittest.main()
