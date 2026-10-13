"""Synthetic-only adversarial and stable-ID regressions for the read-only QA layer."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.factory_extensions.sense_integrity.audit import KINDS, audit, digest


ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "catalog/language_registry.v1.json"


def source(approved=False):
    return {"source_id": "fixture.synthetic.v1", "origin_url": "https://example.invalid/fixture",
            "publisher": "Synthetic test", "dataset_version": "v1",
            "retrieval_id": "fixture", "license_id": "LicenseRef-Test",
            "record_locator": "fixture", "artifact_sha256": "a" * 64 if approved else None,
            "publication_approved": approved, "fixture_only": not approved}


def lex(rid, lang="de", lemma="Bank", script="Latn", pos="noun", **kw):
    return {"lexeme_id": rid, "language": lang, "script": script, "lemma": lemma,
            "surface": lemma, "pos": pos, "direction": "ltr",
            "source": source(), **kw}


def sense(rid, owner, concept, definition, **kw):
    return {"sense_id": rid, "lexeme_id": owner, "concept_id": concept,
            "definition": definition, "source": source(), **kw}


def write(directory, records):
    directory.mkdir()
    for kind in KINDS:
        with (directory / (kind + ".jsonl")).open("w", encoding="utf-8") as stream:
            for record in records.get(kind, []):
                stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class SenseIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.records = {
            "lexemes": [lex("lex.de.bank.a"), lex("lex.de.bank.b")],
            "senses": [
                sense("sense.de.money", "lex.de.bank.a", "concept.money", "financial institution"),
                sense("sense.de.river", "lex.de.bank.b", "concept.river", "river's edge")],
            "translations": [], "relations": [], "examples": []}

    def run_audit(self, records=None, name="report", previous=None, dispositions=None,
                  ledger=None, shard=0, shards=1):
        target = self.base / ("input" + name)
        write(target, records if records is not None else self.records)
        output = self.base / name
        audit(target, output, previous=previous, ledger=ledger, dispositions=dispositions,
              registry=REGISTRY, shard=shard, shards=shards)
        return output

    def test_distinct_homographs_and_polysemy_are_retained_with_review_group(self):
        output = self.run_audit()
        groups = read_jsonl(output / "candidates.jsonl")
        self.assertEqual(len([x for x in groups if x["record_type"] == "group"]), 1)
        self.assertEqual({x["lexeme_id"] for x in groups if x["record_type"] == "member"},
                         {"lex.de.bank.a", "lex.de.bank.b"})
        self.assertEqual(len(read_jsonl(output / "merge-plan.jsonl")), 4)
        stats = json.loads((output / "per-language.json").read_text())["languages"]
        self.assertEqual(stats["de"]["unresolved_ambiguity"], 1)
        self.assertEqual(stats["de"]["accepted_senses"], 0)
        self.assertEqual(len(stats), 100)

    def test_distinct_scripts_accents_pos_register_dialect_homograph_never_collapsed(self):
        items = [
            lex("lex.a.aa", lang="ar", script="Arab", lemma="ها"),
            lex("lex.a.bb", lang="ar", script="Latn", lemma="ha"),
            lex("lex.d.aa", lemma="schon", pos="adverb"),
            lex("lex.d.bb", lemma="schön", pos="adverb"),
            lex("lex.d.cc", lemma="Bank", pos="verb"),
            lex("lex.d.dd", lemma="Bank", dialect="Swiss"),
            lex("lex.d.ee", lemma="Bank", register="formal"),
            lex("lex.d.ff", lemma="Bank", homograph_key="separate") ]
        rows = {kind: [] for kind in KINDS}
        rows["lexemes"] = items
        out = self.run_audit(rows)
        self.assertEqual(read_jsonl(out / "candidates.jsonl"), [])
        self.assertEqual(len(read_jsonl(out / "merge-plan.jsonl")), len(items))

    def test_incremental_stable_id_changes_and_removals_are_blocked_in_report(self):
        previous = self.base / "previous"
        write(previous, self.records)
        updated = copy.deepcopy(self.records)
        updated["lexemes"][0]["lemma"] = "Banke"
        updated["senses"][0]["definition"] = "a financial company"
        updated["senses"].pop()
        out = self.run_audit(updated, previous=previous)
        codes = {i["code"] for i in read_jsonl(out / "conflicts.jsonl")}
        self.assertIn("stable_id_reassigned", codes)
        self.assertIn("definition_changed", codes)
        self.assertIn("stable_id_removed", codes)
        actions = {i["action"] for i in read_jsonl(out / "merge-plan.jsonl")}
        self.assertIn("retain_previous_missing", actions)
        self.assertIn("retain_id_review", actions)

    def test_orphans_cross_language_links_and_concept_identity_collision(self):
        row = copy.deepcopy(self.records)
        row["lexemes"].append(lex("lex.en.tree", lang="en", lemma="tree"))
        row["senses"].append(sense("sense.en.tree", "lex.en.tree", "concept.tree", "tree"))
        row["translations"].append({
            "translation_id": "tr.bad", "from_sense_id": "sense.de.money",
            "to_sense_id": "sense.en.tree", "language": "de", "text": "tree",
            "equivalence": "exact", "source": source()})
        row["relations"].append({
            "relation_id": "rel.bad", "from_lexeme_id": "lex.de.bank.a",
            "to_lexeme_id": "lex.en.tree", "kind": "variant", "source": source()})
        row["examples"].append({
            "example_id": "ex.bad", "sense_id": "sense.de.money",
            "language": "en", "script": "Latn", "text": "Bank", "source": source()})
        row["senses"].append(sense("sense.orphan", "lex.absent", "concept.orphan", "missing"))
        row["senses"][1]["concept_id"] = "lex.en.tree"
        out = self.run_audit(row)
        codes = {x["code"] for x in read_jsonl(out / "conflicts.jsonl")}
        self.assertTrue({"cross_language_translation", "cross_language_relation",
                         "cross_language_example", "orphan_sense",
                         "concept_identity_collision"} <= codes, codes)

    def test_source_approval_requires_real_ledger_match_and_separate_counts(self):
        row = {"lexemes": [lex("lex.approved")],
               "senses": [sense("sense.approved", "lex.approved", "concept.approved", "attested")],
               "translations": [], "relations": [], "examples": []}
        for x in row["lexemes"] + row["senses"]:
            x["source"] = source(approved=True)
        ledger = self.base / "ledger.json"
        ledger.write_text(json.dumps({"sources": [{
            "source_id": "fixture.synthetic.v1", "dataset_version": "v1",
            "retrieval": {"sha256": "a" * 64},
            "license": {"id": "LicenseRef-Test"}, "status": "approved"
        }]}), encoding="utf-8")
        out = self.run_audit(row, ledger=ledger)
        lang = json.loads((out / "per-language.json").read_text())["languages"]["de"]
        self.assertEqual(lang["accepted_senses"], 1)
        self.assertEqual(lang["unresolved_ambiguity"], 0)
        ledger.write_text(json.dumps({"sources": [{
            "source_id": "fixture.synthetic.v1", "dataset_version": "v2",
            "retrieval": {"sha256": "a" * 64},
            "license": {"id": "LicenseRef-Test"}, "status": "approved"
        }]}), encoding="utf-8")
        out2 = self.run_audit(row, "changed-approval", ledger=ledger)
        codes = {x["code"] for x in read_jsonl(out2 / "conflicts.jsonl")}
        self.assertIn("stale_or_mismatched_provenance", codes)
        lang2 = json.loads((out2 / "per-language.json").read_text())["languages"]["de"]
        self.assertEqual(lang2["accepted_senses"], 0)

    def test_approved_sense_with_unapproved_parent_is_never_proposed(self):
        row = {"lexemes": [lex("lex.parent")],
               "senses": [sense("sense.child", "lex.parent", "concept.child", "sourced")],
               "translations": [], "relations": [], "examples": []}
        row["senses"][0]["source"] = source(approved=True)
        ledger = self.base / "parent-ledger.json"
        ledger.write_text(json.dumps({"sources": [{
            "source_id": "fixture.synthetic.v1", "dataset_version": "v1",
            "retrieval": {"sha256": "a" * 64},
            "license": {"id": "LicenseRef-Test"}, "status": "approved"
        }]}), encoding="utf-8")
        out = self.run_audit(row, name="unapproved-parent", ledger=ledger)
        actions = {x["id"]: x["action"] for x in read_jsonl(out / "merge-plan.jsonl")}
        self.assertEqual(actions["sense.child"], "review_new")
        self.assertEqual(json.loads((out / "per-language.json").read_text())["languages"]["de"]["accepted_senses"], 0)

    def test_reviewer_disposition_is_audit_only_not_a_merge(self):
        baseline = self.run_audit()
        group = next(x for x in read_jsonl(baseline / "candidates.jsonl") if x["record_type"] == "group")
        dispositions = self.base / "dispositions.jsonl"
        dispositions.write_text(json.dumps({
            "candidate_id": group["candidate_id"], "disposition": "distinct",
            "reviewer": "fixture.reviewer", "review_reference": "synthetic:test"
        }) + "\n")
        next_report = self.run_audit(name="reviewed", dispositions=dispositions)
        stats = json.loads((next_report / "per-language.json").read_text())["languages"]["de"]
        self.assertEqual(stats["unresolved_ambiguity"], 0)
        self.assertEqual(stats["reviewer_dispositions"]["distinct"], 1)
        self.assertEqual(len(read_jsonl(next_report / "merge-plan.jsonl")), 4)

    def test_entity_id_reuse_across_lexeme_and_sense_is_blocked(self):
        row = copy.deepcopy(self.records)
        row["senses"][0]["sense_id"] = "lex.de.bank.a"
        out = self.run_audit(row, name="cross-kind")
        codes = {x["code"] for x in read_jsonl(out / "conflicts.jsonl")}
        self.assertIn("cross_kind_identity_collision", codes)

    def test_checkpoint_replay_and_tamper_detection(self):
        output = self.run_audit()
        input_dir = self.base / "inputreport"
        first = audit(input_dir, output, registry=REGISTRY, resume=True)
        second = json.loads((output / "checkpoint.json").read_text())
        self.assertEqual(first, second)
        (output / "candidates.jsonl").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "corrupted checkpoint"):
            audit(input_dir, output, registry=REGISTRY, resume=True)
        with self.assertRaises(FileExistsError):
            audit(input_dir, output, registry=REGISTRY)

    def test_input_order_independent_reports_and_disjoint_shards(self):
        a = self.run_audit()
        shuffled = copy.deepcopy(self.records)
        for values in shuffled.values():
            values.reverse()
        b = self.run_audit(shuffled, name="reordered")
        for name in ("candidates.jsonl", "conflicts.jsonl", "merge-plan.jsonl", "per-language.json"):
            self.assertEqual((a / name).read_bytes(), (b / name).read_bytes())
        output1 = self.run_audit(name="shard1", shard=0, shards=2)
        output2 = self.run_audit(name="shard2", shard=1, shards=2)
        groups = [x["candidate_id"] for out in (output1, output2)
                  for x in read_jsonl(out / "candidates.jsonl") if x["record_type"] == "group"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(set(groups)), 1)

    def test_duplicate_ids_and_bad_json_fail_closed(self):
        rows = copy.deepcopy(self.records)
        rows["lexemes"].append(copy.deepcopy(rows["lexemes"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate lexemes ID"):
            self.run_audit(rows)
        clean = self.base / "malformed"
        write(clean, self.records)
        with (clean / "senses.jsonl").open("a", encoding="utf-8") as stream:
            stream.write('{"sense_id":"x","sense_id":"y"}\n')
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            audit(clean, self.base / "no-output", registry=REGISTRY)


if __name__ == "__main__":
    unittest.main()
