import unittest
import zlib
import json
from optimizer import SVGOptimizer

class TestSVGOptimizer(unittest.TestCase):
    def setUp(self):
        self.opt = SVGOptimizer()

    def test_valid_svg_optimization(self):
        svg = '<svg viewBox="0 0 100 100"><path d="M10.1234 20.5678 L30 40" fill="#FF0000"/></svg>'
        token = self.opt.optimize(svg, "c123", "CC0", "hash123")

        decompressed = json.loads(zlib.decompress(token).decode('utf-8'))
        self.assertEqual(decompressed['c'], "c123")
        self.assertEqual(decompressed['l'], "CC0")

        geom = decompressed['g']
        self.assertEqual(geom[0]['t'], 'viewBox')
        self.assertEqual(geom[0]['v'], '0 0 100 100')
        self.assertEqual(geom[1]['t'], 'path')
        self.assertEqual(decompressed['d'][geom[1]['d']], 'M10.123 20.568 L30 40')

    def test_unsafe_svg_rejected(self):
        unsafe_svgs = [
            '<svg><script>alert(1)</script></svg>',
            '<svg onload="alert(1)"></svg>',
            '<svg><image href="http://evil.com/img.png"/></svg>',
            '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"><svg></svg>',
            '<svg xmlns:xlink="http://www.w3.org/1999/xlink"><use xlink:href="http://evil.com/img.svg#a"/></svg>',
        ]

        for svg in unsafe_svgs:
            with self.assertRaises(ValueError):
                self.opt.optimize(svg, "c1", "CC0", "h1")

    def test_safe_on_attributes_allowed(self):
        svg = '<svg viewBox="0 0 100 100"><polygon points="0,0 10,10" /></svg>'
        token = self.opt.optimize(svg, "c1", "CC0", "h1")
        self.assertTrue(len(token) > 0)

    def test_invalid_paths_rejected(self):
        with self.assertRaises(ValueError):
            self.opt.optimize('<svg><path /></svg>', "c1", "CC0", "h1")
        with self.assertRaises(ValueError):
            self.opt.optimize('<svg><polygon /></svg>', "c1", "CC0", "h1")

    def test_nested_transforms(self):
        svg = '<svg><g transform="translate(10, 10)"><g transform="scale(2)"><rect x="0" y="0" width="10" height="10"/></g></g></svg>'
        token = self.opt.optimize(svg, "c1", "CC0", "h1")
        decompressed = json.loads(zlib.decompress(token).decode('utf-8'))
        rect = decompressed['g'][0]
        self.assertEqual(rect['transform'], 'translate(10, 10) scale(2)')

    def test_geometry_overflow_size_limit(self):
        paths = "".join([f'<path d="M{i} {i} L{i+1} {i+1}"/>' for i in range(1000)])
        svg = f'<svg>{paths}</svg>'
        with self.assertRaises(ValueError):
            self.opt.optimize(svg, "c1", "CC0", "h1")

    def test_determinism(self):
        svg = '<svg viewBox="0 0 100 100"><rect x="10" y="10" width="50" height="50"/></svg>'
        token1 = self.opt.optimize(svg, "c1", "CC0", "h1")
        token2 = self.opt.optimize(svg, "c1", "CC0", "h1")
        self.assertEqual(token1, token2)

    def test_bounds_verification(self):
        svg = '<svg viewBox="0 0 100 100"><path d="M10 20 L30 40"/></svg>'
        token = self.opt.optimize(svg, "c1", "CC0", "h1")
        self.assertTrue(self.opt.verify_bounds(svg, token))

    def test_ellipse_and_rect_attributes(self):
        svg = '<svg><ellipse cx="10" cy="10" rx="5" ry="3" /><rect x="0" y="0" width="10" height="10" rx="2" ry="2"/></svg>'
        token = self.opt.optimize(svg, "c1", "CC0", "h1")
        decompressed = json.loads(zlib.decompress(token).decode('utf-8'))
        ellipse = decompressed['g'][0]
        rect = decompressed['g'][1]
        self.assertEqual(ellipse['rx'], '5')
        self.assertEqual(ellipse['ry'], '3')
        self.assertEqual(rect['rx'], '2')
        self.assertEqual(rect['ry'], '2')

    def test_palette_dedup_case_insensitive(self):
        svg = '<svg><path d="M0 0 L1 1" fill="#FF0000"/><path d="M1 1 L2 2" fill="#ff0000"/></svg>'
        token = self.opt.optimize(svg, "c1", "CC0", "h1")
        decompressed = json.loads(zlib.decompress(token).decode('utf-8'))
        self.assertEqual(len(decompressed['p']), 1)
        self.assertEqual(decompressed['p']['0'], '#ff0000')

if __name__ == '__main__':
    unittest.main()
