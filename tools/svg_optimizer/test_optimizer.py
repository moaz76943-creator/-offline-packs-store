import unittest
import zlib
import json
from tools.svg_optimizer.optimizer import SvgOptimizer, UnsafeSvgError, UnsupportedSvgFeatureError, SvgSizeExceededError

class TestSvgOptimizer(unittest.TestCase):
    def setUp(self):
        self.optimizer = SvgOptimizer()
        self.evidence = {'source_id': 'fixture-vector', 'dataset_version': '2026.10', 'artifact_sha256': 'abc'}

    def test_basic_optimization(self):
        svg = '<svg viewBox="0 0 100 100"><path d="M 10.1234 10.5678 L 20 20" fill="#000" /></svg>'
        res = self.optimizer.optimize(svg, 'test-1', 'hash1', self.evidence)
        decoded = json.loads(zlib.decompress(res))
        self.assertEqual(decoded['concept_id'], 'test-1')
        self.assertEqual(decoded['paths'][0]['d'], 'M 10.123 10.568 L 20 20')
        self.assertEqual(decoded['paths'][0]['fill'], '#000')

    def test_unsafe_entity(self):
        svg = '<!DOCTYPE svg [<!ENTITY x "test">]><svg>&x;</svg>'
        with self.assertRaises(UnsafeSvgError):
            self.optimizer.optimize(svg, 'test-1', 'hash1', self.evidence)

    def test_unsafe_script(self):
        svg = '<svg><script>alert(1)</script></svg>'
        with self.assertRaises(UnsupportedSvgFeatureError):
            self.optimizer.optimize(svg, 'test-1', 'hash1', self.evidence)

    def test_unsafe_onclick(self):
        svg = '<svg><path d="M0 0" onclick="alert(1)"/></svg>'
        with self.assertRaises(UnsafeSvgError):
            self.optimizer.optimize(svg, 'test-1', 'hash1', self.evidence)

    def test_unsafe_href(self):
        svg = '<svg xmlns:xlink="http://www.w3.org/1999/xlink"><image xlink:href="http://example.com/img.png" /></svg>'
        with self.assertRaises(UnsupportedSvgFeatureError):
            self.optimizer.optimize(svg, 'test-1', 'hash1', self.evidence)

        svg2 = '<svg xmlns:xlink="http://www.w3.org/1999/xlink"><path d="M0 0" xlink:href="http://example.com/img.png" /></svg>'
        with self.assertRaises(UnsafeSvgError):
            self.optimizer.optimize(svg2, 'test-1', 'hash1', self.evidence)

    def test_oversized_input(self):
        svg = '<svg>' + '<path d="M0 0" />' * 20000 + '</svg>'
        with self.assertRaises(SvgSizeExceededError):
            self.optimizer.optimize(svg, 'test-1', 'hash1', self.evidence)

    def test_deduplication(self):
        svg = '<svg><path d="M 0 0 L 10 10" /><path d="M 0 0 L 10 10" /></svg>'
        res = self.optimizer.optimize(svg, 'test-1', 'hash1', self.evidence)
        decoded = json.loads(zlib.decompress(res))
        self.assertEqual(len(decoded['paths']), 1)

    def test_normalization_rect(self):
        svg = '<svg><rect x="10" y="10" width="20" height="20" /></svg>'
        res = self.optimizer.optimize(svg, 'test-1', 'hash1', self.evidence)
        decoded = json.loads(zlib.decompress(res))
        self.assertEqual(decoded['paths'][0]['d'], 'M 10 10 L 30 10 L 30 30 L 10 30 Z')

    def test_identical_output(self):
        svg1 = '<svg><path d="M0 0" fill="#000" /></svg>'
        svg2 = '<svg><path fill="#000" d="M0 0" /></svg>'
        res1 = self.optimizer.optimize(svg1, 'test-1', 'hash1', self.evidence)
        res2 = self.optimizer.optimize(svg2, 'test-1', 'hash1', self.evidence)
        self.assertEqual(res1, res2)

    def test_inherited_attributes(self):
        svg = '<svg><g fill="#f00" transform="translate(10, 20)"><path d="M 0 0 L 10 10" transform="scale(2)" stroke="#00f" /></g></svg>'
        res = self.optimizer.optimize(svg, 'test-1', 'hash1', self.evidence)
        decoded = json.loads(zlib.decompress(res))
        self.assertEqual(len(decoded['paths']), 1)
        self.assertEqual(decoded['paths'][0]['transform'], 'translate(10,20) scale(2)')
        self.assertEqual(decoded['paths'][0]['fill'], '#f00')
        self.assertEqual(decoded['paths'][0]['stroke'], '#00f')

    def test_invalid_path(self):
        svg = '<svg><path d="0 0" /></svg>'
        with self.assertRaises(UnsupportedSvgFeatureError):
            self.optimizer.optimize(svg, 'test-1', 'hash1', self.evidence)

    def test_supported_complex_curves(self):
        svg = '<svg viewBox="0 0 100 100"><path d="M 0 0 A 10 10 0 0 1 20 20 C 30 30 40 40 50 50 Q 60 60 70 70" /></svg>'
        res = self.optimizer.optimize(svg, 'test-1', 'hash1', self.evidence)
        decoded = json.loads(zlib.decompress(res))
        self.assertEqual(len(decoded['paths']), 1)

    def test_unsupported_attribute(self):
        svg = '<svg><path d="M 0 0 L 10 10" opacity="0.5" /></svg>'
        with self.assertRaises(UnsupportedSvgFeatureError):
            self.optimizer.optimize(svg, 'test-1', 'hash1', self.evidence)

    def test_geometry_overflow(self):
        svg = '<svg viewBox="0 0 10 10"><path d="M 100 100 L 200 200" /></svg>'
        from tools.svg_optimizer.optimizer import SvgOptimizationError
        with self.assertRaises(SvgOptimizationError) as e:
            self.optimizer.optimize(svg, 'test-1', 'hash1', self.evidence)
        self.assertIn("Geometry significantly overflows viewBox", str(e.exception))

if __name__ == '__main__':
    unittest.main()
