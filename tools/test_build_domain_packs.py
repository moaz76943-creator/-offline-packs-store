"""Bounds for the manual Gemini dictionary sample. No network and no production writes."""
import gzip
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

import build_domain_packs as packs

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "dictionary_pipeline.yml"


def write_sample(path, rows):
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


class DictionaryPipelineWorkflowTest(unittest.TestCase):
    def test_workflow_is_manual_bounded_and_does_not_publish(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        loaded = yaml.safe_load(text)
        # PyYAML 1.1 treats the unquoted key "on" as a boolean.
        trigger = loaded["on"] if "on" in loaded else loaded[True]
        self.assertEqual(list(trigger), ["workflow_dispatch"])
        self.assertEqual(loaded["permissions"], {"contents": "read"})
        self.assertLessEqual(loaded["jobs"]["build-dictionary"]["timeout-minutes"], 30)
        inputs = trigger["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["batch_size"]["default"], "10")
        self.assertEqual(
            loaded["jobs"]["build-dictionary"]["steps"][-1]["with"]["name"],
            "unverified-candidate-research-output",
        )
        for forbidden in (
            "git push",
            "git commit",
            "gh workflow run",
            "[skip ci]",
            "|| true",
            "github.event.inputs",
            "contents: write",
            "actions: write",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn("UNVERIFIED CANDIDATE / RESEARCH OUTPUT", text)
        self.assertIn("legal/ledger", text)


class BuildDomainPacksBoundsTest(unittest.TestCase):
    def test_rejects_unbounded_or_unsafe_arguments_before_using_a_key(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(packs.main(["--input", "x", "--out-dir", "y", "--lang", "de", "--batch-size", "0"]), 2)
            self.assertEqual(packs.main(["--input", "x", "--out-dir", "y", "--lang", "de", "--batch-size", "26"]), 2)
            self.assertEqual(packs.main(["--input", "x", "--out-dir", "y", "--lang", "../de", "--batch-size", "10"]), 2)
            self.assertEqual(packs.main(["--input", "missing.gz", "--out-dir", "out", "--lang", "de", "--batch-size", "1"]), 1)

    def test_does_not_consult_the_unread_data_dictionaries_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = os.getcwd()
            self.addCleanup(os.chdir, previous)
            os.chdir(root)
            checkpoint = root / "data" / "dictionaries"
            checkpoint.mkdir(parents=True)
            (checkpoint / "de.json").write_text(json.dumps({"Haus": {"cefr": "A1"}}), encoding="utf-8")
            sample = root / "sample.jsonl.gz"
            out = root / "dist_packs"
            write_sample(sample, [{"word": "Haus", "senses": [{"glosses": ["house"]}]}])
            calls = []

            def fake(prompt, api_key):
                calls.append(prompt)
                return json.dumps([
                    {"word": "Haus", "cefr": "A1", "domain": "home", "definition": "house"},
                ])

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch.object(packs, "call_gemini", fake):
                code = packs.main([
                    "--input", str(sample),
                    "--out-dir", str(out),
                    "--lang", "de",
                    "--batch-size", "1",
                ])
            self.assertEqual(code, 0)
            self.assertEqual(len(calls), 1)
            self.assertIn("Haus", calls[0])

    def test_classifies_only_the_bounded_sample_and_stays_in_the_output_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample = root / "sample.jsonl.gz"
            out = root / "dist_packs"
            write_sample(sample, [
                {"word": "Haus", "senses": [{"glosses": ["house"]}]},
                {"word": "Katze", "senses": [{"glosses": ["cat"]}]},
                {"word": "Baum", "senses": [{"glosses": ["tree"]}]},
            ])
            calls = []

            def fake(prompt, api_key):
                calls.append((prompt, api_key))
                return json.dumps([
                    {"word": "Haus", "cefr": "A1", "domain": "../legal", "definition": "house"},
                    {"word": "Katze", "cefr": "A1", "domain": "animals", "definition": "cat"},
                ])

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch.object(packs, "call_gemini", fake):
                code = packs.main([
                    "--input", str(sample),
                    "--out-dir", str(out),
                    "--lang", "de",
                    "--batch-size", "2",
                ])
            self.assertEqual(code, 0)
            self.assertEqual(len(calls), 1)
            self.assertIn("Haus", calls[0][0])
            self.assertNotIn("Baum", calls[0][0])
            written = sorted(path.name for path in out.iterdir())
            self.assertEqual(written, ["de_animals.json", "de_legal.json"])
            self.assertTrue(all(path.parent == out.resolve() for path in out.iterdir()))

    def test_malformed_model_output_fails_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample = root / "sample.jsonl.gz"
            out = root / "dist_packs"
            write_sample(sample, [{"word": "Haus", "senses": [{"glosses": ["house"]}]}])
            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch.object(
                packs, "call_gemini", lambda prompt, api_key: "not json"
            ):
                code = packs.main([
                    "--input", str(sample),
                    "--out-dir", str(out),
                    "--lang", "de",
                    "--batch-size", "1",
                ])
            self.assertEqual(code, 1)
            self.assertFalse(out.exists() and any(out.iterdir()))


if __name__ == "__main__":
    unittest.main()
