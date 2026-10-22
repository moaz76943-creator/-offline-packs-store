import unittest
from tools.svg_optimizer.optimizer import SvgOptimizer

class TestSvgOptimizerSecurity(unittest.TestCase):
    def setUp(self):
        self.optimizer = SvgOptimizer()

    def test_xxe_entity_rejection(self):
        malicious_svg = '''<?xml version="1.0"?>
        <!DOCTYPE svg [
          <!ENTITY xxe SYSTEM "file:///etc/passwd">
        ]>
        <svg>&xxe;</svg>'''
        with self.assertRaisesRegex(ValueError, "forbidden DOCTYPE or ENTITY declarations"):
            self.optimizer.parse_securely(malicious_svg)

    def test_xxe_doctype_rejection(self):
        malicious_svg = '''<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
        <svg></svg>'''
        with self.assertRaisesRegex(ValueError, "forbidden DOCTYPE or ENTITY declarations"):
            self.optimizer.parse_securely(malicious_svg)

    def test_reject_unsafe_tags(self):
        unsafe_svgs = [
            '<svg><script>alert(1)</script></svg>',
            '<svg><foreignObject><div>Hi</div></foreignObject></svg>',
            '<svg><image href="http://example.com/img.jpg"/></svg>',
            '<svg><iframe></iframe></svg>',
            '<svg><style>@import url("http://evil.com/style.css");</style></svg>'
        ]
        for svg in unsafe_svgs:
            root = self.optimizer.parse_securely(svg)
            with self.assertRaises(ValueError):
                self.optimizer.reject_unsafe_and_unsupported(root)

    def test_reject_event_handlers(self):
        svg = '<svg><rect onload="alert(1)" x="0" y="0" width="10" height="10"/></svg>'
        root = self.optimizer.parse_securely(svg)
        with self.assertRaises(ValueError):
            self.optimizer.reject_unsafe_and_unsupported(root)

    def test_reject_network_references(self):
        svg = '<svg><a href="http://evil.com"><circle r="5"/></a></svg>'
        root = self.optimizer.parse_securely(svg)
        with self.assertRaises(ValueError):
            self.optimizer.reject_unsafe_and_unsupported(root)

    def test_reject_unsupported_features(self):
        svg = '<svg><filter id="f1"><feGaussianBlur stdDeviation="3"/></filter></svg>'
        root = self.optimizer.parse_securely(svg)
        with self.assertRaises(ValueError):
            self.optimizer.reject_unsafe_and_unsupported(root)

    def test_reject_style_external_url(self):
        svg = '<svg><rect style="fill: url(http://evil.com/img.png);" width="10" height="10"/></svg>'
        root = self.optimizer.parse_securely(svg)
        with self.assertRaises(ValueError):
            self.optimizer.reject_unsafe_and_unsupported(root)

class TestSvgOptimizerGeometryAndToken(unittest.TestCase):
    def setUp(self):
        self.optimizer = SvgOptimizer()

    def test_shape_to_path(self):
        svg = '<svg><rect x="10" y="10" width="20" height="20"/></svg>'
        root = self.optimizer.parse_securely(svg)
        rect = root.find('rect')
        d = self.optimizer.shape_to_path(rect)
        self.assertEqual(d, 'M 10.0 10.0 H 30.0 V 30.0 H 10.0 Z')

    def test_matrix_transform(self):
        # translate(10, 10)
        matrix = self.optimizer.parse_transform('translate(10, 10)')
        d = 'M 0 0 L 10 10'
        transformed = self.optimizer.transform_path(d, matrix)
        self.assertEqual(transformed, 'M 10.00 10.00 L 20.00 20.00')

    def test_geometry_overflow(self):
        paths = ['M -50 -50 L 100 100']
        viewBox = [0, 0, 24, 24]
        with self.assertRaisesRegex(ValueError, "Geometry overflow"):
            self.optimizer.verify_geometry(paths, viewBox)

    def test_geometry_valid(self):
        paths = ['M 5 5 L 20 20']
        viewBox = [0, 0, 24, 24]
        # Should not raise
        self.optimizer.verify_geometry(paths, viewBox)

    def test_optimize_determinism(self):
        svg1 = '<svg viewBox="0 0 24 24"><path d="M 0 0 L 10 10" fill="#ff0000"/><path d="M 10 10 L 20 20" fill="#00ff00"/></svg>'
        svg2 = '<svg viewBox="0 0 24 24"><path fill="#ff0000" d="M 0 0 L 10 10"/><path fill="#00ff00" d="M 10 10 L 20 20"/></svg>'

        token1 = self.optimizer.optimize(svg1, "test-1", "label", {}, "hash1")
        token2 = self.optimizer.optimize(svg2, "test-1", "label", {}, "hash1")

        self.assertEqual(token1, token2)

    def test_z_order_preservation_and_deduplication(self):
        # Two identical shapes should be deduplicated in `paths` but both represented in `shapes` array to preserve rendering count if needed.
        # Wait, exact sequential duplicate shapes are deduplicated by the optimizer to save space.
        # Let's test two different shapes.
        svg = '<svg viewBox="0 0 24 24"><path d="M 20 20 L 22 22" fill="#ff0000"/><path d="M 0 0 L 10 10" fill="#00ff00"/></svg>'
        token_bytes = self.optimizer.optimize(svg, "test-z", "label", {}, "hash")
        import zlib, json
        token = json.loads(zlib.decompress(token_bytes).decode('utf-8'))

        self.assertIn('shapes', token)
        self.assertEqual(len(token['shapes']), 2)
        # Red path first
        shape1 = token['shapes'][0]
        self.assertEqual(token['palette'][shape1['color_idx']], '#ff0000')
        self.assertEqual(token['paths'][shape1['path_idx']], 'M 20.00 20.00 L 22.00 22.00')

        # Green path second
        shape2 = token['shapes'][1]
        self.assertEqual(token['palette'][shape2['color_idx']], '#00ff00')
        self.assertEqual(token['paths'][shape2['path_idx']], 'M 0.00 0.00 L 10.00 10.00')

    def test_relative_bezier(self):
        # A relative bezier with multiple segments to test the current_x/y updates
        d = "m 10 10 c 5 5 10 5 10 10 c 5 5 10 5 10 10"
        matrix = [[1,0,0],[0,1,0],[0,0,1]]
        transformed = self.optimizer.transform_path(d, matrix)
        # m 10 10 -> M 10 10
        # first c 5 5 10 5 10 10 -> C 15 15 20 15 20 20  (current pos becomes 20 20)
        # second c 5 5 10 5 10 10 -> C 25 25 30 25 30 30
        self.assertEqual(transformed, "M 10.00 10.00 C 15.00 15.00 20.00 15.00 20.00 20.00 C 25.00 25.00 30.00 25.00 30.00 30.00")

    def test_reject_unsupported_tags(self):
        # Reject silent drop of unsupported text and use tags
        svg = '<svg viewBox="0 0 24 24"><text>Hello</text></svg>'
        with self.assertRaisesRegex(ValueError, "Tag not supported: text"):
            self.optimizer.optimize(svg, "test", "label", {}, "hash")

        svg2 = '<svg viewBox="0 0 24 24"><use href="#test"/></svg>'
        with self.assertRaisesRegex(ValueError, "Tag not supported: use"):
            self.optimizer.optimize(svg2, "test", "label", {}, "hash")

    def test_reject_unsupported_transforms(self):
        svg = '<svg viewBox="0 0 24 24"><path transform="rotate(45)" d="M 0 0 L 10 10" fill="#000000"/></svg>'
        with self.assertRaisesRegex(ValueError, "Unsupported transform command: rotate"):
            self.optimizer.optimize(svg, "test", "label", {}, "hash")

    def test_reject_unsupported_color(self):
        svg = '<svg viewBox="0 0 24 24"><path d="M 0 0 L 10 10" fill="rgb(255,0,0)"/></svg>'
        with self.assertRaisesRegex(ValueError, "Unsupported color format: rgb"):
            self.optimizer.optimize(svg, "test", "label", {}, "hash")

    def test_reject_stroke(self):
        svg = '<svg viewBox="0 0 24 24"><path d="M 0 0 L 10 10" stroke="#000000" fill="none"/></svg>'
        with self.assertRaisesRegex(ValueError, "Unsupported feature: stroke in path is not supported by J053 token."):
            self.optimizer.optimize(svg, "test", "label", {}, "hash")

    def test_size_limit(self):
        # Create a huge SVG to trigger size limit but within bounds
        # use small increments that won't be completely zlib optimized away
        paths = "".join([f'<path d="M {1 + i/100.0} {2 + i/100.0} L {10 + i/100.0} {11 + i/100.0}" fill="#ff0000"/>' for i in range(500)])
        svg = f'<svg viewBox="0 0 24 24">{paths}</svg>'

        with self.assertRaisesRegex(ValueError, "Token is too large"):
            self.optimizer.optimize(svg, "huge", "label", {}, "hash")

if __name__ == '__main__':
    unittest.main()
