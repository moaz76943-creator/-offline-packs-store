import unittest
import os
import shutil
import tempfile
from pathlib import Path
from tools.change_impact.engine import DependencyGraph, ImpactAnalyzer

class TestChangeImpactAdvanced(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.base_path = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_indirect_imports_and_tests(self):
        (self.base_path / "core.py").write_text("def do_something(): pass\n")
        (self.base_path / "feature.py").write_text("import core\n")
        (self.base_path / "test_feature.py").write_text("import feature\n")

        analyzer = ImpactAnalyzer(self.base_path)
        report = analyzer.get_impact_report(["core.py"])

        self.assertIn("core.py", report["impacted_files"])
        self.assertIn("feature.py", report["impacted_files"])
        self.assertIn("test_feature.py", report["impacted_tests"])
        self.assertFalse(report["widen_scope"])

    def test_widen_scope_on_uncertainty(self):
        (self.base_path / "core.py").write_text("def do_something(): pass\n")
        (self.base_path / "feature.py").write_text("import core\n")
        # Dynamic import makes this uncertain
        (self.base_path / "test_feature.py").write_text("feature = __import__('feature')\n")

        analyzer = ImpactAnalyzer(self.base_path)
        report = analyzer.get_impact_report(["core.py"])

        self.assertTrue(report["widen_scope"])

    def test_mixed_python_dart(self):
        (self.base_path / "mixed.py").write_text("import utils\n")
        (self.base_path / "utils.py").write_text("pass\n")
        (self.base_path / "main.dart").write_text("import 'helper.dart';\n")
        (self.base_path / "helper.dart").write_text("void main() {}\n")

        analyzer = ImpactAnalyzer(self.base_path)
        report = analyzer.get_impact_report(["utils.py", "helper.dart"])

        self.assertIn("mixed.py", report["impacted_files"])
        if shutil.which("dart"):
            self.assertIn("main.dart", report["impacted_files"])

    def test_renames_and_missing(self):
        # Ensure non-existent files passed as changed are ignored safely
        (self.base_path / "core.py").write_text("pass\n")

        analyzer = ImpactAnalyzer(self.base_path)
        report = analyzer.get_impact_report(["core.py", "missing.py"])

        self.assertEqual(report["changed_files"], ["core.py"])
        self.assertNotIn("missing.py", report["impacted_files"])

if __name__ == '__main__':
    unittest.main()
