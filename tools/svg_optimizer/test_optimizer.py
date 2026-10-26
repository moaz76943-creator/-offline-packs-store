import unittest
from tools.svg_optimizer.optimizer import SVGOptimizer

class TestSVGOptimizer(unittest.TestCase):
    def setUp(self):
        self.optimizer = SVGOptimizer()

    def test_basic_conversion(self):
        svg = """<svg viewBox="0 0 100 100">
            <path d="M 10 10 L 90 90" fill="#FF0000" />
        </svg>"""
        result = self.optimizer.optimize(svg, "test_concept", "Test Label", "Author", "Source")
        self.assertEqual(result["token"]["concept_id"], "test_concept")
        self.assertEqual(result["token"]["paths"], ["M 10 10 L 90 90"])
        self.assertEqual(result["token"]["palette"], ["#f00"])

    def test_reject_script(self):
        svg = """<svg viewBox="0 0 100 100">
            <script>alert(1)</script>
            <path d="M 10 10 L 90 90" fill="#FF0000" />
        </svg>"""
        with self.assertRaises(ValueError) as context:
            self.optimizer.optimize(svg, "test_concept", "Test Label", "Author", "Source")
        self.assertIn("Unsupported tag found: script", str(context.exception))

    def test_reject_foreign_object(self):
        svg = """<svg viewBox="0 0 100 100">
            <foreignObject width="100" height="100">
                <body xmlns="http://www.w3.org/1999/xhtml">
                    <p>Some text</p>
                </body>
            </foreignObject>
            <path d="M 10 10 L 90 90" fill="#FF0000" />
        </svg>"""
        with self.assertRaises(ValueError) as context:
            self.optimizer.optimize(svg, "test_concept", "Test Label", "Author", "Source")
        self.assertIn("Unsupported tag found: foreignobject", str(context.exception))

    def test_reject_event_handler(self):
        svg = """<svg viewBox="0 0 100 100" onclick="alert(1)">
            <path d="M 10 10 L 90 90" fill="#FF0000" />
        </svg>"""
        with self.assertRaises(ValueError) as context:
            self.optimizer.optimize(svg, "test_concept", "Test Label", "Author", "Source")
        self.assertIn("Event handler found: onclick", str(context.exception))

    def test_reject_external_reference(self):
        svg = """<svg viewBox="0 0 100 100">
            <image href="http://example.com/image.png" width="100" height="100" />
        </svg>"""
        with self.assertRaises(ValueError) as context:
            self.optimizer.optimize(svg, "test_concept", "Test Label", "Author", "Source")

    def test_transform_normalization(self):
        svg = """<svg viewBox="0 0 100 100">
            <g transform="translate(10, 10)">
                <path d="M 0 0 L 10 10" fill="#FF0000" />
            </g>
        </svg>"""
        result = self.optimizer.optimize(svg, "test_concept", "Test Label", "Author", "Source")
        # Should translate the path to M 10 10 L 20 20
        self.assertEqual(result["token"]["paths"], ["M 10 10 L 20 20"])

    def test_quantization(self):
        svg = """<svg viewBox="0 0 100 100">
            <path d="M 10.12345 10.98765 L 90.1111 90.9999" fill="#FF0000" />
        </svg>"""
        result = self.optimizer.optimize(svg, "test_concept", "Test Label", "Author", "Source")
        # Quantizes to 3 decimal places
        self.assertEqual(result["token"]["paths"], ["M 10.123 10.988 L 90.111 91"])

    def test_determinism(self):
        svg1 = """<svg viewBox="0 0 100 100">
            <path d="M 10 10 L 90 90" fill="#FF0000" />
        </svg>"""
        svg2 = """<svg viewBox="0 0 100 100">
            <path d="M  10  10  L  90  90" fill="#ff0000" />
        </svg>"""
        res1 = self.optimizer.optimize(svg1, "test_concept", "Test Label", "Author", "Source")
        res2 = self.optimizer.optimize(svg2, "test_concept", "Test Label", "Author", "Source")
        self.assertEqual(res1["hash"], res2["hash"])
        self.assertEqual(res1["compressed_bytes"], res2["compressed_bytes"])

    def test_size_limit(self):
        path_data = " ".join([f"L {i} {i}" for i in range(1000)])
        svg = f"""<svg viewBox="0 0 100 100">
            <path d="M 0 0 {path_data}" fill="#FF0000" />
        </svg>"""
        with self.assertRaises(ValueError) as context:
            self.optimizer.optimize(svg, "test_concept", "Test Label", "Author", "Source")
        self.assertIn("Token is too large", str(context.exception))

    def test_invalid_xml(self):
        with self.assertRaises(ValueError) as context:
            self.optimizer.optimize("<svg><path", "test_concept", "Test Label", "Author", "Source")
        self.assertIn("Invalid XML or security violation", str(context.exception))

    def test_round_trip_verifier(self):
        # The optimizer performs round-trip in optimize() which implicitly checks sizes and decoded paths.
        # This test ensures we cover the success case nicely.
        svg = """<svg viewBox="0 0 100 100">
            <path d="M 10 10 L 90 90" fill="#FF0000" />
        </svg>"""
        # Should not raise any ValueError about round trip
        self.optimizer.optimize(svg, "test_concept", "Test Label", "Author", "Source")

if __name__ == "__main__":
    unittest.main()
