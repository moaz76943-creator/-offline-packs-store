import unittest
from tools.svg_optimizer.optimizer import SVGOptimizer
from tools.visual_lexicon.core import decode_token

class TestSVGOptimizer(unittest.TestCase):
    def setUp(self):
        self.optimizer = SVGOptimizer()
        self.concept_id = "test.concept"
        self.version = 1
        self.semantic_label = "Test Label"
        self.license = "CC0-1.0"
        self.source = "https://example.com"
        self.source_hash = "abc123hash"

    def test_valid_svg_conversion(self):
        svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
            <path d="M 10 20 L 30 40 Z" fill="#FF0000"/>
        </svg>"""
        res, manifest = self.optimizer.optimize(svg, self.concept_id, self.version, self.semantic_label, self.license, self.source, self.source_hash)
        self.assertTrue(len(res) > 0)
        self.assertTrue(len(res) < 2048)

        token = decode_token(res)
        self.assertEqual(token['concept_id'], self.concept_id)
        self.assertEqual(token['version'], self.version)
        self.assertEqual(token['semantic_label'], self.semantic_label)
        self.assertEqual(token['viewBox'], [0, 0, 100, 100])
        self.assertEqual(token['paths'], ["M 10 20 L 30 40 Z"])
        self.assertEqual(token['palette'], ["#FF0000"])

        self.assertEqual(manifest['license'], self.license)
        self.assertEqual(manifest['source'], self.source)
        self.assertEqual(manifest['source_hash'], self.source_hash)

    def test_xxe_rejection(self):
        svg = """<!DOCTYPE svg PUBLIC '-//W3C//DTD SVG 1.1//EN' 'http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd'>
        <svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'></svg>"""
        with self.assertRaisesRegex(ValueError, "Unsafe XML"):
            self.optimizer.optimize(svg, self.concept_id, self.version, self.semantic_label)

        svg2 = """<?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE svg [
        <!ENTITY xxe SYSTEM "file:///etc/passwd">
        ]>
        <svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><path d="M 0 0 Z"/></svg>"""
        with self.assertRaisesRegex(ValueError, "Unsafe XML"):
            self.optimizer.optimize(svg2, self.concept_id, self.version, self.semantic_label)

    def test_script_rejection(self):
        svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
            <script>alert(1)</script>
            <path d="M 0 0 Z"/>
        </svg>"""
        with self.assertRaisesRegex(ValueError, "Unsupported element"):
            self.optimizer.optimize(svg, self.concept_id, self.version, self.semantic_label)

    def test_event_handler_rejection(self):
        svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
            <path d="M 0 0 Z" onclick="alert(1)"/>
        </svg>"""
        with self.assertRaisesRegex(ValueError, "Unsafe attribute"):
            self.optimizer.optimize(svg, self.concept_id, self.version, self.semantic_label)

    def test_remote_reference_rejection(self):
        svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
            <path d="M 0 0 Z" href="http://example.com/malicious"/>
        </svg>"""
        with self.assertRaisesRegex(ValueError, "Unsafe attribute"):
            self.optimizer.optimize(svg, self.concept_id, self.version, self.semantic_label)

    def test_unsupported_geometry(self):
        svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
            <rect x="10" y="10" width="20" height="20"/>
        </svg>"""
        with self.assertRaisesRegex(ValueError, "Unsupported element"):
            self.optimizer.optimize(svg, self.concept_id, self.version, self.semantic_label)

    def test_coordinate_quantization(self):
        svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0.123 0.456 100.999 100.001">
            <path d="M 10.123456 20.98765 L 30.5 40 Z" fill="#000000"/>
        </svg>"""
        res, _ = self.optimizer.optimize(svg, self.concept_id, self.version, self.semantic_label)
        token = decode_token(res)
        self.assertEqual(token['viewBox'], [0.12, 0.46, 101, 100])
        self.assertEqual(token['paths'], ["M 10.12 20.99 L 30.5 40 Z"])

    def test_deduplication(self):
        svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
            <path d="M 10 20 L 30 40 Z" fill="#ff0000"/>
            <path d="M 10.00 20.000 L 30 40 Z" fill="#FF0000"/>
            <path d="M 50 60 L 70 80 Z" stroke="#ff0000"/>
        </svg>"""
        res, _ = self.optimizer.optimize(svg, self.concept_id, self.version, self.semantic_label)
        token = decode_token(res)
        self.assertEqual(len(token['paths']), 2)
        self.assertEqual(len(token['palette']), 1)
        self.assertEqual(token['palette'], ["#FF0000"])

    def test_deterministic_output(self):
        svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
            <path d="M 10 20 L 30 40 Z" fill="#FF0000"/>
        </svg>"""
        res1, _ = self.optimizer.optimize(svg, self.concept_id, self.version, self.semantic_label)
        res2, _ = self.optimizer.optimize(svg, self.concept_id, self.version, self.semantic_label)
        self.assertEqual(res1, res2)

    def test_size_limits(self):
        paths = "".join([f'<path d="M {i} {i} L {i+1} {i+1} Z" fill="#000000"/>' for i in range(100)])
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
            {paths}
        </svg>"""
        with self.assertRaisesRegex(ValueError, "Maximum of 50 paths allowed"):
            self.optimizer.optimize(svg, self.concept_id, self.version, self.semantic_label)

    def test_geometry_overflow(self):
        svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
            <path d="M 500 500 L 600 600 Z" fill="#FF0000"/>
        </svg>"""
        with self.assertRaisesRegex(ValueError, "Path geometry overflowed viewBox"):
            self.optimizer.optimize(svg, self.concept_id, self.version, self.semantic_label)

    def test_nested_transforms(self):
        svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
            <g transform="translate(10, 10)">
                <path d="M 0 0 L 10 10 Z" transform="scale(2)" fill="#FF0000"/>
            </g>
        </svg>"""
        res, _ = self.optimizer.optimize(svg, self.concept_id, self.version, self.semantic_label)
        token = decode_token(res)
        self.assertEqual(token['paths'], ["M 10 10 L 30 30 Z"])

    def test_invalid_path(self):
         svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
            <path d="M 10 20 L 30 40 C 1 2 3 4 5 6 Z" transform="matrix(0.5, 0.5, -0.5, 0.5, 0, 0)" fill="#FF0000"/>
        </svg>"""
         with self.assertRaisesRegex(ValueError, "Cannot safely apply complex matrix transform"):
             self.optimizer.optimize(svg, self.concept_id, self.version, self.semantic_label)

if __name__ == '__main__':
    unittest.main()
