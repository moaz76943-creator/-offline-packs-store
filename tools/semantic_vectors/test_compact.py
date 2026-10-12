"""Compact vector safety, round trip and visual contract tests."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from compact import VectorError, compile_svg, decode_token, render_svg, normalize_path

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M2 3 L12 5 Q14 5 16 10 Z" fill="none" stroke="#123456" stroke-width="2"/></svg>'


class CompactTests(unittest.TestCase):
    def test_canonical_and_small(self):
        a = compile_svg(SVG)
        self.assertEqual(a, compile_svg(SVG))
        self.assertLess(len(a), 2048)
        shapes = decode_token(a)
        self.assertEqual(shapes[0][1], "M2 3L12 5Q14 5 16 10Z")
        self.assertIn('<path ', render_svg(a, 'House'))
        self.assertIn('aria-label="House"', render_svg(a, 'House'))

    def test_quantized_geometry(self):
        self.assertEqual(normalize_path('M2.04 3.06 L9.99 10.01'), 'M2 3.1L10 10')

    def test_rejects_malicious_svg(self):
        payloads = [
            '<svg viewBox="0 0 24 24"><script>alert(1)</script></svg>',
            '<svg viewBox="0 0 24 24"><foreignObject/></svg>',
            '<svg viewBox="0 0 24 24"><path onload="alert(1)" d="M1 2"/></svg>',
            '<svg viewBox="0 0 24 24"><image href="https://example.org/img"/></svg>',
            '<svg viewBox="0 0 24 24"><text font-family="evil"/></svg>',
            '<!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><svg viewBox="0 0 24 24"/>',
            '<svg viewBox="0 0 24 24"><style>@import url(x)</style></svg>',
            '<svg viewBox="0 0 24 24"><a href="javascript:alert(1)"/></svg>',
            '<svg viewBox="0 0 24 24"><path d="M1e100 2"/></svg>',
            '<svg viewBox="0 0 24 24"><path d="M1 2 L40 40"/></svg>',
        ]
        for payload in payloads:
            with self.subTest(payload=payload[:55]), self.assertRaises(VectorError):
                compile_svg(payload)

    def test_decompression_bomb_and_corruption(self):
        import base64, zlib
        compressed = b'CVT1:' + base64.urlsafe_b64encode(zlib.compress(b'x' * 25000, 9))
        for bad in (compressed, b'CVT1:invalid', b'CVT2:abc', b'CVT1:'):
            with self.subTest(bad=bad[:20]), self.assertRaises(VectorError):
                decode_token(bad)

    def test_excessive_geometry_and_size_rejected(self):
        complex_svg = SVG.replace('M2 3 L12 5 Q14 5 16 10 Z', ' '.join(['M1 1'] + ['L12 12'] * 90))
        with self.assertRaises(VectorError):
            compile_svg(complex_svg)
        with self.assertRaises(VectorError):
            compile_svg(SVG, limit=10)

    def test_accessibility_escapes_labels(self):
        self.assertIn('A&amp;B &lt;C&gt;', render_svg(compile_svg(SVG), 'A&B <C>'))
        with self.assertRaises(VectorError):
            render_svg(compile_svg(SVG), '')


if __name__ == '__main__':
    unittest.main()
