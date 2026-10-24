import unittest
import zlib
import json
from tools.svg_optimizer.optimizer import SvgOptimizer

class TestSvgOptimizer(unittest.TestCase):
    def setUp(self):
        self.opt = SvgOptimizer()
        self.meta = {
            'concept_id': 'test-123',
            'semantic_label': 'Test Icon'
        }

    def test_xxe_rejection(self):
        svg = '<?xml version="1.0"?><!DOCTYPE svg []><svg></svg>'
        with self.assertRaises(ValueError):
            self.opt.parse_securely(svg)

        svg_entity = '<?xml version="1.0"?><!ENTITY xxe "test"><svg></svg>'
        with self.assertRaises(ValueError):
            self.opt.parse_securely(svg_entity)

    def test_unsafe_elements_rejected(self):
        unsafe = ['<script>alert()</script>', '<foreignObject></foreignObject>', '<use href="#foo"/>']
        for elem in unsafe:
            svg = f'<svg viewBox="0 0 100 100">{elem}</svg>'
            with self.assertRaises(ValueError):
                self.opt.optimize_to_token(svg, self.meta)

    def test_unsupported_attributes_rejected(self):
        svg = '<svg viewBox="0 0 100 100"><path d="M 0 0" stroke="black"/></svg>'
        with self.assertRaises(ValueError):
            self.opt.optimize_to_token(svg, self.meta)

        svg = '<svg viewBox="0 0 100 100"><path d="M 0 0" style="fill:red"/></svg>'
        with self.assertRaises(ValueError):
            self.opt.optimize_to_token(svg, self.meta)

    def test_relative_paths_rejected(self):
        svg = '<svg viewBox="0 0 100 100"><path d="M 0 0 l 10 10"/></svg>'
        with self.assertRaises(ValueError):
            self.opt.optimize_to_token(svg, self.meta)

    def test_unsupported_shapes_rejected(self):
        svg = '<svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="10"/></svg>'
        with self.assertRaises(ValueError):
            self.opt.optimize_to_token(svg, self.meta)

    def test_geometry_normalization_and_quantization(self):
        svg = '<svg viewBox="0 0 100 100"><path d="M 10.1234 10 L 20 20 Z" fill="#fff" /></svg>'
        token_bytes, _ = self.opt.optimize_to_token(svg, self.meta)
        token_dict = json.loads(zlib.decompress(token_bytes).decode('utf-8'))

        self.assertEqual(token_dict['paths'][0], 'M 10.123 10 L 20 20 Z')
        self.assertEqual(token_dict['palette'][0], '#ffffff')

    def test_line_conversion(self):
        svg = '<svg viewBox="0 0 100 100"><line x1="0" y1="0" x2="50" y2="50" fill="#fff" /></svg>'
        token_bytes, _ = self.opt.optimize_to_token(svg, self.meta)
        token_dict = json.loads(zlib.decompress(token_bytes).decode('utf-8'))

        self.assertEqual(token_dict['paths'][0], 'M 0 0 L 50 50')

    def test_deduplication(self):
        svg = '<svg viewBox="0 0 100 100"><path d="M 0 0 L 10 10"/><path d="M 0 0 L 10 10"/></svg>'
        token_bytes, _ = self.opt.optimize_to_token(svg, self.meta)
        token_dict = json.loads(zlib.decompress(token_bytes).decode('utf-8'))

        self.assertEqual(len(token_dict['paths']), 1)

    def test_deterministic_output(self):
        svg1 = '<svg viewBox="0 0 100 100"><path d="M 10 10 L 20 20 Z" fill="#ffffff" /></svg>'
        svg2 = '<svg viewBox="0 0 100 100"><path d="M 10 10 L 20 20 Z" fill="#fff" /></svg>'

        b1, h1 = self.opt.optimize_to_token(svg1, self.meta)
        b2, h2 = self.opt.optimize_to_token(svg2, self.meta)

        self.assertEqual(b1, b2)
        self.assertEqual(h1, h2)

if __name__ == '__main__':
    unittest.main()
