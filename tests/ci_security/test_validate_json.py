"""Execute the actual JSON-validation CI shell with hostile filenames safely."""
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "validate_json.yml"


def workflow_script():
    document = WORKFLOW.read_text(encoding="utf-8")
    if "run: |\n" not in document:
        raise AssertionError("Expected inline JSON validator workflow script")
    return textwrap.dedent(document.split("run: |\n", 1)[1])


def invoke(folder):
    return subprocess.run(
        ["bash", "-e", "-u", "-o", "pipefail", "-c", workflow_script()],
        cwd=folder, capture_output=True, text=True, timeout=10, check=False,
    )


class JsonWorkflowFilenameSafety(unittest.TestCase):
    def test_shell_substitution_in_filename_never_executes(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            (directory / 'data"$(touch EXECUTED)".json').write_text("{}", encoding="utf-8")
            result = invoke(td)
            self.assertFalse((directory / "EXECUTED").exists(),
                             f"arbitrary command executed: {result.stderr}")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_unicode_spaces_quotes_and_newlines_in_valid_file_names(self):
        with tempfile.TemporaryDirectory() as td:
            for name in ("arabic بيت.json", "a'quote.json", "line\nfeed.json"):
                (Path(td) / name).write_text('{"s": "ß بيت"}', encoding="utf-8")
            result = invoke(td)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_reject_malformed_json_with_error_status(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "broken json.json").write_text('{"a":', encoding="utf-8")
            self.assertNotEqual(invoke(td).returncode, 0)

    def test_zero_json_files_is_a_successful_noop(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(invoke(td).returncode, 0)


if __name__ == "__main__":
    unittest.main()
