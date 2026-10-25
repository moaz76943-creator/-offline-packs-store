import unittest
from tools.svg_optimizer.optimizer import SvgOptimizer

class TestSvgOptimizer(unittest.TestCase):
    def setUp(self):
        self.opt = SvgOptimizer()
        self.metadata = {
            'concept_id': 'test-1',
            'semantic_label': 'test',
            'license': 'CC0-1.0',
            'source_hash': 'abcdef123456',
            'author': 'Alice'
        }

    def test_xxe_prevention(self):
        unsafe_svg = '<!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><svg>&xxe;</svg>'
        with self.assertRaisesRegex(ValueError, "Unsafe XML"):
            self.opt.parse_svg(unsafe_svg)

    def test_unsafe_elements_rejected(self):
        unsafe_tags = ['script', 'foreignObject', 'image', 'text', 'use']
        for tag in unsafe_tags:
            svg = f'<svg viewBox="0 0 100 100"><{tag}></{tag}></svg>'
            with self.assertRaisesRegex(ValueError, "Unsupported element"):
                self.opt.optimize(svg, self.metadata)

    def test_unsafe_attributes_rejected(self):
        svg = '<svg viewBox="0 0 100 100"><path d="M0 0" onclick="alert(1)"/></svg>'
        with self.assertRaisesRegex(ValueError, "Unsafe attribute"):
            self.opt.optimize(svg, self.metadata)

    def test_external_references_rejected(self):
        svg = '<svg viewBox="0 0 100 100"><path href="http://evil.com" d="M0 0"/></svg>'
        with self.assertRaisesRegex(ValueError, "External references not allowed"):
            self.opt.optimize(svg, self.metadata)

    def test_unsupported_nested_transforms_rejected(self):
        svg = '<svg viewBox="0 0 100 100"><g transform="rotate(45)"><path d="M 0 0 L 10 10"/></g></svg>'
        with self.assertRaisesRegex(ValueError, "Unsupported transform"):
            self.opt.optimize(svg, self.metadata)

    def test_translate_scale_transforms_allowed(self):
        # We now partially support translate and scale without crashing,
        # let's make sure it doesn't raise Unsupported Transform.
        svg = '<svg viewBox="0 0 100 100"><g transform="translate(10, 10)"><path d="M 0 0 L 10 10"/></g></svg>'
        token = self.opt.optimize(svg, self.metadata)
        self.assertTrue(len(token['paths']) > 0)

    def test_relative_path_commands_rejected(self):
        svg = '<svg viewBox="0 0 100 100"><path d="m 0 0 l 10 10"/></svg>'
        with self.assertRaisesRegex(ValueError, "Unsupported relative path commands"):
            self.opt.optimize(svg, self.metadata)

    def test_unsupported_shapes_rejected(self):
        svg = '<svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="40"/></svg>'
        with self.assertRaisesRegex(ValueError, "Unsupported element"):
            self.opt.optimize(svg, self.metadata)

    def test_line_converted_to_path(self):
        svg = '<svg viewBox="0 0 100 100"><line x1="10" y1="10" x2="90" y2="90"/></svg>'
        token = self.opt.optimize(svg, self.metadata)
        self.assertEqual(token['paths'][0], 'M 10 10 L 90 90')

    def test_path_quantization(self):
        svg = '<svg viewBox="0 0 100 100"><path d="M 10.123 20.456 L 30.789 40.00"/></svg>'
        token = self.opt.optimize(svg, self.metadata)
        self.assertEqual(token['paths'][0], 'M 10.12 20.46 L 30.79 40')

    def test_path_deduplication(self):
        svg = '<svg viewBox="0 0 100 100"><path d="M 0 0 L 10 10"/><path d="M 0 0 L 10 10"/></svg>'
        token = self.opt.optimize(svg, self.metadata)
        self.assertEqual(len(token['paths']), 1)

    def test_exceeding_max_paths(self):
        paths = "".join([f'<path d="M 0 {i} L 10 {i}"/>' for i in range(51)])
        svg = f'<svg viewBox="0 0 100 100">{paths}</svg>'
        with self.assertRaisesRegex(ValueError, "Exceeded maximum allowed paths"):
            self.opt.optimize(svg, self.metadata)

    def test_metadata_preservation(self):
        svg = '<svg viewBox="0 0 100 100"><path d="M 0 0 L 10 10"/></svg>'
        token = self.opt.optimize(svg, self.metadata)
        self.assertEqual(token['license'], 'CC0-1.0')
        self.assertEqual(token['source_hash'], 'abcdef123456')
        self.assertEqual(token['author'], 'Alice')

if __name__ == '__main__':
    unittest.main()
