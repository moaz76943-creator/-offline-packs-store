"""Adversarial offline QA for the strict directed graph, including pair isolation."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.factory_extensions.directed_translation_scale.graph import execute, AdmissionError

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "catalog/language_registry.v1.json"
SHA = "a" * 64

def write(path, data):
    path.write_text(json.dumps(data,ensure_ascii=False,sort_keys=True)+"\n",encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()

class DirectedGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.src = {"source_id":"src.attested","origin_url":"https://example.org/dataset",
                    "publisher":"Independent test publisher","dataset_version":"v1",
                    "retrieval_id":"snapshot.v1","license_id":"CC0-1.0",
                    "record_locator":"row 1","artifact_sha256":SHA,
                    "publication_approved":True,"fixture_only":False}
        self.ledger = {"schema_version":"1.0.0","sources":[{
            "source_id":"src.attested","origin_url":"https://example.org/dataset",
            "publisher":"Independent test publisher","dataset_version":"v1",
            "license":{"id":"CC0-1.0"},"retrieval":{"sha256":SHA},
            "review":{"reviewer":"independent test"},"status":"APPROVED_FOR_REDISTRIBUTION"}]}
        self.ledger_path = self.dir/"sources.json"
        self.lex_path = self.dir/"lexical.json"
        self.cand_path = self.dir/"candidate.jsonl"
        self.review_path = self.dir/"reviews.json"
        self.db = self.dir/"graph.sqlite"
        self.lexemes = [
            {"lexeme_id":"lex.de.bank","language":"de","script":"Latn","lemma":"Bank","surface":"Bank","source":self.src},
            {"lexeme_id":"lex.en.bank","language":"en","script":"Latn","lemma":"bank","surface":"bank","source":self.src},
            {"lexeme_id":"lex.en.river","language":"en","script":"Latn","lemma":"bank","surface":"bank","source":self.src},
            {"lexeme_id":"lex.ar.bank","language":"ar","script":"Arab","lemma":"مصرف","surface":"مصرف","source":self.src},
        ]
        self.senses = [
            {"sense_id":"sense.de.bank","lexeme_id":"lex.de.bank","concept_id":"concept.finance","source":self.src},
            {"sense_id":"sense.en.bank","lexeme_id":"lex.en.bank","concept_id":"concept.finance","source":self.src},
            {"sense_id":"sense.en.river","lexeme_id":"lex.en.river","concept_id":"concept.river","source":self.src},
            {"sense_id":"sense.ar.bank","lexeme_id":"lex.ar.bank","concept_id":"concept.finance","source":self.src},
        ]
        self.candidate = {
            "translation_id":"tr.de.en.finance",
            "source_language":"de","target_language":"en",
            "from_sense_id":"sense.de.bank","to_sense_id":"sense.en.bank",
            "translation_text":"bank","equivalence":"exact","context":"banking","domain":"finance",
            "register":"neutral","dialect":"standard","source":self.src,
            "evidence":{"kind":"direct_sense_attestation","from_sense_id":"sense.de.bank",
                        "to_sense_id":"sense.en.bank","source_sha256":SHA,"record_locator":"row 1"}
        }
        self.install()

    def install(self):
        write(self.ledger_path,self.ledger)
        write(self.lex_path,{"contract_version":"1.0.0","document_id":"doc.test",
                            "lexemes":self.lexemes,"senses":self.senses,
                            "translations":[],"examples":[],"relations":[]})
        self.candidate_sha = write(self.cand_path,self.candidate)

    def run_graph(self,*,candidate=True,reviews=False,**kwargs):
        return execute(registry=REGISTRY,sources=self.ledger_path,
                       lexical=self.lex_path,lexical_sha=hashlib.sha256(self.lex_path.read_bytes()).hexdigest(),
                       candidates=self.cand_path if candidate else None,
                       candidates_sha=self.candidate_sha if candidate else None,
                       reviews=self.review_path if reviews else None,
                       reviews_sha=hashlib.sha256(self.review_path.read_bytes()).hexdigest() if reviews else None,
                       database=self.db,**kwargs)

    def test_missing_rights_never_admits_fixture_senses(self):
        self.ledger["sources"]=[]
        self.install()
        result=self.run_graph()
        self.assertEqual(result["admitted_senses"],0)
        self.assertEqual(result["counts"]["verified"],0)
        self.assertEqual(result["counts"]["blocked"],1)

    def test_single_direction_not_reverse(self):
        result=self.run_graph(matrix=self.dir/"coverage.json")
        self.assertEqual(result["counts"]["review_required"],1)
        self.assertEqual(result["counts"]["verified"],0)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM edges WHERE source_language='en' AND target_language='de'").fetchone()[0],0)
        pairs={(x["source_language"],x["target_language"]):x
               for x in json.loads((self.dir/"coverage.json").read_text())["pairs"]}
        self.assertEqual(len(pairs),9900)
        self.assertEqual(pairs[("de","en")]["status"],"review_required")
        self.assertEqual(pairs[("en","de")]["status"],"unavailable")

    def test_no_pivot_or_transitive_edge(self):
        second=dict(self.candidate,translation_id="tr.en.ar.finance",source_language="en",
                    target_language="ar",from_sense_id="sense.en.bank",
                    to_sense_id="sense.ar.bank",translation_text="مصرف",
                    evidence=dict(self.candidate["evidence"],from_sense_id="sense.en.bank",
                                  to_sense_id="sense.ar.bank"))
        self.cand_path.write_text("".join(json.dumps(x,ensure_ascii=False)+"\n"
                                              for x in [self.candidate,second]),encoding="utf-8")
        self.candidate_sha=hashlib.sha256(self.cand_path.read_bytes()).hexdigest()
        result=self.run_graph()
        self.assertEqual(result["counts"]["review_required"],2)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM edges WHERE source_language='de' AND target_language='ar'").fetchone()[0],0)

    def test_homograph_wrong_sense_is_blocked(self):
        self.candidate["to_sense_id"]="sense.en.river"
        self.candidate["evidence"]["to_sense_id"]="sense.en.river"
        self.install()
        self.assertEqual(self.run_graph()["blocked_reasons"]["WRONG_SENSE_CONCEPT"],1)

    def test_script_swap_is_blocked(self):
        self.candidate["to_script"]="Arab"
        self.install()
        self.assertEqual(self.run_graph()["blocked_reasons"]["SCRIPT_IDENTITY_SWAP"],1)

    def test_language_swap_is_blocked(self):
        self.candidate["source_language"]="en"
        self.install()
        self.assertEqual(self.run_graph()["blocked_reasons"]["LANGUAGE_IDENTITY_SWAP"],1)

    def test_unattested_target_text_is_blocked(self):
        self.candidate["translation_text"]="Bank"
        self.install()
        self.assertEqual(self.run_graph()["blocked_reasons"]["TARGET_LEXEME_TEXT_MISMATCH"],1)

    def test_missing_direct_evidence_is_blocked(self):
        del self.candidate["evidence"]
        self.install()
        self.assertEqual(self.run_graph()["blocked_reasons"]["DIRECT_SENSE_EVIDENCE_MISSING"],1)

    def test_stale_source_version_is_blocked(self):
        self.candidate["source"]=dict(self.src,dataset_version="old")
        self.install()
        self.assertEqual(self.run_graph()["blocked_reasons"]["SOURCE_RIGHTS_OR_PROVENANCE_BLOCKED"],1)

    def test_missing_license_is_blocked(self):
        self.ledger["sources"][0]["license"]={}
        self.install()
        self.assertEqual(self.run_graph()["counts"]["verified"],0)
        self.assertEqual(self.run_graph()["counts"]["blocked"],1)

    def test_fixture_only_cannot_be_published(self):
        self.candidate["source"]=dict(self.src,fixture_only=True)
        self.install()
        self.assertEqual(self.run_graph()["counts"]["review_required"],0)

    def test_review_bound_to_exact_direction_and_snapshot(self):
        self.install()
        write(self.review_path,{"schema_version":"1.0.0","candidate_sha256":self.candidate_sha,
            "reviews":[{"translation_id":self.candidate["translation_id"],"decision":"approved",
                        "from_sense_id":"sense.de.bank","to_sense_id":"sense.en.bank",
                        "source_language":"de","target_language":"en",
                        "source_sha256":SHA,"candidate_sha256":self.candidate_sha,
                        "reviewer":"independent editorial reviewer","review_id":"review.123",
                        "evidence_locator":"editorial ledger item 4"}]})
        self.assertEqual(self.run_graph(reviews=True)["counts"]["verified"],1)

    def test_wrong_direction_review_does_not_verify(self):
        self.install()
        write(self.review_path,{"schema_version":"1.0.0","candidate_sha256":self.candidate_sha,
            "reviews":[{"translation_id":self.candidate["translation_id"],"decision":"approved",
                        "from_sense_id":"sense.en.bank","to_sense_id":"sense.de.bank",
                        "source_language":"en","target_language":"de",
                        "source_sha256":SHA,"candidate_sha256":self.candidate_sha,
                        "reviewer":"editor","review_id":"review.1","evidence_locator":"item 1"}]})
        self.assertEqual(self.run_graph(reviews=True)["counts"]["review_required"],1)

    def test_stale_candidate_snapshot_refused(self):
        self.candidate["domain"]="changed"
        write(self.cand_path,self.candidate)
        with self.assertRaisesRegex(AdmissionError,"STALE_OR_INVALID_SNAPSHOT"):
            self.run_graph()

    def test_duplicate_translation_id_rejected(self):
        self.install()
        self.cand_path.write_text(json.dumps(self.candidate)+"\n"+json.dumps(self.candidate)+"\n")
        self.candidate_sha=hashlib.sha256(self.cand_path.read_bytes()).hexdigest()
        result=self.run_graph()
        self.assertEqual(result["counts"]["review_required"],1)
        self.assertEqual(result["blocked_reasons"]["DUPLICATE_EDGE_ID"],1)

    def test_pr79_document_adapter_blocks_misplaced_reverse(self):
        doc={"contract_version":"1.0.0","document_id":"pairs.test","source_language":"de",
             "target_language":"en","translations":[dict(self.candidate,source_language="en")]}
        self.candidate_sha=write(self.cand_path,doc)
        self.assertEqual(self.run_graph()["blocked_reasons"]["LANGUAGE_IDENTITY_SWAP"],1)

    def test_shard_is_deterministic(self):
        self.install()
        idx=int(hashlib.sha256(self.candidate["translation_id"].encode()).hexdigest(),16)%4
        r=self.run_graph(shard_count=4,shard_index=idx)
        self.assertEqual(r["counts"]["shard_candidates"],1)

    def test_interface_language_separate_from_edge(self):
        r=self.run_graph(interface_language="ja")
        self.assertEqual(r["interface_language"],"ja")
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT source_language,target_language FROM edges").fetchone(),("de","en"))

    def test_noncanonical_interface_rejected(self):
        with self.assertRaisesRegex(AdmissionError,"NONCANONICAL_INTERFACE_LANGUAGE"):
            self.run_graph(interface_language="xx-NOT-REGISTERED")

if __name__ == "__main__":
    unittest.main()
