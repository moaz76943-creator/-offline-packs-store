import unittest
from tools.svg_optimizer.optimizer import SvgOptimizer

class TestSvgOptimizerSecurity(unittest.TestCase):
    def setUp(self):
        self.optimizer = SvgOptimizer()
        self.concept_id = "test.concept"
        self.semantic_label = "Test Label"

    def test_reject_doctype(self):
        svg = '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd"><svg><path d="M 0 0 L 1 1" /></svg>'
        with self.assertRaisesRegex(ValueError, "Unsafe XML"):
            self.optimizer.optimize(svg, self.concept_id, self.semantic_label)

    def test_reject_entity(self):
        svg = '<!ENTITY xxe SYSTEM "file:///etc/passwd"><svg><text>&xxe;</text></svg>'
        with self.assertRaisesRegex(ValueError, "Unsafe XML"):
            self.optimizer.optimize(svg, self.concept_id, self.semantic_label)

    def test_reject_script(self):
        svg = '<svg><script>alert(1)</script></svg>'
        with self.assertRaisesRegex(ValueError, "Unsupported element: script"):
            self.optimizer.optimize(svg, self.concept_id, self.semantic_label)

    def test_reject_foreignObject(self):
        svg = '<svg><foreignObject></foreignObject></svg>'
        with self.assertRaisesRegex(ValueError, "Unsupported element: foreignObject"):
            self.optimizer.optimize(svg, self.concept_id, self.semantic_label)

    def test_reject_event_handlers(self):
        svg = '<svg><path d="M 0 0 L 1 1" onclick="alert(1)" /></svg>'
        with self.assertRaisesRegex(ValueError, "Event handler not allowed: onclick"):
            self.optimizer.optimize(svg, self.concept_id, self.semantic_label)

    def test_reject_external_references(self):
        svg = '<svg><image href="http://example.com/image.png" /></svg>'
        with self.assertRaisesRegex(ValueError, "Unsupported element: image"):
            self.optimizer.optimize(svg, self.concept_id, self.semantic_label)

        svg2 = '<svg><use href="#some-id" /></svg>'
        with self.assertRaisesRegex(ValueError, "Unsupported element: use"):
            self.optimizer.optimize(svg2, self.concept_id, self.semantic_label)

    def test_reject_stroke(self):
        svg = '<svg><path d="M 0 0 L 1 1" stroke="red" /></svg>'
        with self.assertRaisesRegex(ValueError, "Unsupported attribute: stroke"):
            self.optimizer.optimize(svg, self.concept_id, self.semantic_label)

    def test_reject_style(self):
        svg = '<svg><path d="M 0 0 L 1 1" style="fill: red;" /></svg>'
        with self.assertRaisesRegex(ValueError, "Unsupported attribute: style"):
            self.optimizer.optimize(svg, self.concept_id, self.semantic_label)

class TestSvgOptimizerGeometry(unittest.TestCase):
    def setUp(self):
        self.optimizer = SvgOptimizer()
        self.concept_id = "test.concept"
        self.semantic_label = "Test Label"

    def test_primitive_conversion(self):
        svg = '<svg viewBox="0 0 24 24"><rect x="1" y="1" width="2" height="2" fill="#000" /></svg>'
        token = self.optimizer.optimize(svg, self.concept_id, self.semantic_label)
        self.assertEqual(len(token['paths']), 1)
        self.assertEqual(token['paths'][0], "M 1.0 1.0 L 3.0 1.0 L 3.0 3.0 L 1.0 3.0 Z")

        svg_line = '<svg viewBox="0 0 24 24"><line x1="1" y1="1" x2="10" y2="10" fill="#000" /></svg>'
        token_line = self.optimizer.optimize(svg_line, self.concept_id, self.semantic_label)
        self.assertEqual(token_line['paths'][0], "M 1.0 1.0 L 10.0 10.0")

    def test_transforms(self):
        svg = '<svg><g transform="translate(10, 10)"><rect x="0" y="0" width="10" height="10" /></g></svg>'
        token = self.optimizer.optimize(svg, self.concept_id, self.semantic_label)
        self.assertEqual(token['paths'][0], "M 10.0 10.0 L 20.0 10.0 L 20.0 20.0 L 10.0 20.0 Z")

    def test_reject_rotate(self):
        svg = '<svg><g transform="rotate(45)"><rect x="0" y="0" width="10" height="10" /></g></svg>'
        with self.assertRaisesRegex(ValueError, "Unsupported transform: rotate"):
            self.optimizer.optimize(svg, self.concept_id, self.semantic_label)

    def test_deduplication(self):
        svg = '<svg><rect x="0" y="0" width="10" height="10" fill="#000" /><rect x="0" y="0" width="10" height="10" fill="#FFF" /></svg>'
        token = self.optimizer.optimize(svg, self.concept_id, self.semantic_label)
        # Should be 1 unique path, 2 unique colors
        self.assertEqual(len(token['paths']), 1)
        self.assertEqual(len(token['palette']), 2)
        self.assertEqual(len(token['shapes']), 2)

    def test_deterministic_output(self):
        svg1 = '<svg viewBox="0 0 24 24"><path d="M 0 0 L 1 1 Z" fill="#abc" /></svg>'
        svg2 = '<svg viewBox="0 0 24 24"><path d="M 0 0 L 1 1 Z" fill="#aabbcc" /></svg>'
        token1 = self.optimizer.optimize(svg1, self.concept_id, self.semantic_label)
        token2 = self.optimizer.optimize(svg2, self.concept_id, self.semantic_label)
        self.assertEqual(token1, token2)

    def test_metadata_preservation(self):
        svg = '<svg viewBox="0 0 24 24"><rect x="1" y="1" width="2" height="2" fill="#000" /></svg>'
        token = self.optimizer.optimize(svg, self.concept_id, self.semantic_label, license="CC0-1.0", source="test", source_hash="123")
        self.assertEqual(token['license'], "CC0-1.0")
        self.assertEqual(token['source'], "test")
        self.assertEqual(token['hash'], "123")

    def test_geometry_out_of_bounds(self):
        svg = '<svg viewBox="0 0 10 10"><rect x="15" y="15" width="2" height="2" fill="#000" /></svg>'
        with self.assertRaisesRegex(ValueError, "Geometry out of bounds"):
            self.optimizer.optimize(svg, self.concept_id, self.semantic_label)

        # Test relative path rejection
        svg_rel = '<svg viewBox="0 0 10 10"><path d="M 0 0 l 2 2" fill="#000" /></svg>'
        with self.assertRaisesRegex(ValueError, "Relative path commands are not supported"):
            self.optimizer.optimize(svg_rel, self.concept_id, self.semantic_label)

        # Test Arc geometry out of bounds due to large radius
        svg_arc = '<svg viewBox="0 0 10 10"><path d="M 5 5 A 100 100 0 0 0 6 6" fill="#000" /></svg>'
        with self.assertRaisesRegex(ValueError, "Arc geometry out of bounds"):
            self.optimizer.optimize(svg_arc, self.concept_id, self.semantic_label)

    def test_size_limit(self):
        path = " ".join([f"M {i} {i} L {i+1} {i+1} Z" for i in range(100)])
        # Creating multiple distinct paths to easily breach the 2048 size threshold or the maximum 50 paths threshold
        paths = "".join([f'<path d="M {i} {i} L {i+1} {i+1} Z" fill="#000" />' for i in range(51)])
        svg = f'<svg viewBox="0 0 24 24">{paths}</svg>'

        with self.assertRaisesRegex(ValueError, "Maximum of 50 paths allowed|too large|Failed to encode token"):
            self.optimizer.optimize(svg, self.concept_id, self.semantic_label)

if __name__ == '__main__':
    unittest.main()
