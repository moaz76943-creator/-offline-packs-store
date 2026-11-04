import unittest
import os
import shutil
import tempfile
from pathlib import Path
from tools.change_impact.engine import DependencyGraph, ImpactAnalyzer

class TestChangeImpact(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.base_path = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_python_analyzer(self):
        # Create a simple module structure
        (self.base_path / "a.py").write_text("import b\nfrom sub import c\n")
        (self.base_path / "b.py").write_text("print('b')\n")
        (self.base_path / "sub").mkdir()
        (self.base_path / "sub" / "__init__.py").write_text("")
        (self.base_path / "sub" / "c.py").write_text("print('c')\n")

        analyzer = ImpactAnalyzer(self.base_path)
        analyzer.scan_directory()

        self.assertIn("a.py", analyzer.graph.nodes)
        self.assertIn("b.py", analyzer.graph.edges.get("a.py", set()))
        self.assertIn(os.path.join("sub", "c.py"), analyzer.graph.edges.get("a.py", set()))

    def test_cyclic_import(self):
        (self.base_path / "a.py").write_text("import b\n")
        (self.base_path / "b.py").write_text("import a\n")

        analyzer = ImpactAnalyzer(self.base_path)
        analyzer.scan_directory()

        self.assertIn("b.py", analyzer.graph.edges["a.py"])
        self.assertIn("a.py", analyzer.graph.edges["b.py"])

    def test_syntax_error(self):
        (self.base_path / "a.py").write_text("import b\nvar = \n")

        analyzer = ImpactAnalyzer(self.base_path)
        analyzer.scan_directory()

        self.assertIn("a.py", analyzer.graph.uncertain)

    def test_dynamic_import(self):
        (self.base_path / "a.py").write_text("mod = __import__('b')\n")

        analyzer = ImpactAnalyzer(self.base_path)
        analyzer.scan_directory()

        self.assertIn("a.py", analyzer.graph.uncertain)

    def test_dart_analyzer(self):
        (self.base_path / "a.dart").write_text("import 'b.dart';\n")
        (self.base_path / "b.dart").write_text("void main() {}\n")

        analyzer = ImpactAnalyzer(self.base_path)
        analyzer.scan_directory()

        if shutil.which("dart"):
            self.assertIn("a.dart", analyzer.graph.nodes)
            self.assertIn("b.dart", analyzer.graph.edges.get("a.dart", set()))
        else:
            self.assertIn("a.dart", analyzer.graph.uncertain)

if __name__ == '__main__':
    unittest.main()
