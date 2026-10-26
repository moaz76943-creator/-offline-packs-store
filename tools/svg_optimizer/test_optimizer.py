import unittest
import zlib
import json
from tools.svg_optimizer.optimizer import SVGOptimizer, SVGSecurityError, SVGUnsupportedError, SVGSizeError, SVGParseError

class TestSVGOptimizer(unittest.TestCase):
    def setUp(self):
        self.opt = SVGOptimizer(precision=2)
        self.cid = "concept_123"
        self.lic = "CC0-1.0"

    def test_basic_svg_conversion(self):
        svg = b'<svg viewBox="0 0 24 24"><path d="M1 1 L2 2" fill="#fff"/></svg>'
        res = self.opt.optimize(svg, self.cid, self.lic)

        token = self.opt.decode(res)
        self.assertEqual(token['id'], self.cid)
        self.assertEqual(token['lic'], self.lic)
        self.assertEqual(token['vb'], "0 0 24 24")
        self.assertEqual(len(token['e']), 1)
        self.assertEqual(token['p'], ["#fff"])
        self.assertEqual(token['pd'], ["M1 1 L2 2"])

        self.opt.verify_roundtrip(svg, res)

    def test_security_dtd_entity(self):
        svg = b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n<svg></svg>'
        with self.assertRaises(SVGSecurityError):
            self.opt.optimize(svg, self.cid, self.lic)

        svg = b'<!ENTITY xxe SYSTEM "file:///etc/passwd">\n<svg></svg>'
        with self.assertRaises(SVGSecurityError):
            self.opt.optimize(svg, self.cid, self.lic)

    def test_security_scripts(self):
        svg = b'<svg><script>alert(1)</script></svg>'
        with self.assertRaises(SVGSecurityError):
            self.opt.optimize(svg, self.cid, self.lic)

    def test_security_event_handlers(self):
        svg = b'<svg><path d="M0 0" onclick="alert(1)"/></svg>'
        with self.assertRaises(SVGSecurityError):
            self.opt.optimize(svg, self.cid, self.lic)

    def test_security_foreign_object(self):
        svg = b'<svg><foreignObject></foreignObject></svg>'
        with self.assertRaises(SVGSecurityError):
            self.opt.optimize(svg, self.cid, self.lic)

    def test_security_encoding_bypass(self):
        svg = '<svg><script>alert(1)</script></svg>'.encode('utf-16')
        with self.assertRaises(SVGSecurityError):
            self.opt.optimize(svg, self.cid, self.lic)

    def test_utf16_without_bom_cannot_bypass_entity_scan(self):
        for encoding in ("utf-16le", "utf-16be"):
            with self.subTest(encoding=encoding):
                text = '<!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><svg/>'
                with self.assertRaises(SVGSecurityError):
                    self.opt.optimize(text.encode(encoding), self.cid, self.lic)

    def test_css_url_function_is_case_insensitive(self):
        for name in ("URL", "Url", "uRl"):
            svg = f'<svg><path d="M1 1" fill="{name}(https://example.com/x)"/></svg>'.encode()
            with self.subTest(name=name), self.assertRaises(SVGSecurityError):
                self.opt.optimize(svg, self.cid, self.lic)

    def test_defs_use_not_silently_converted_to_wrong_geometry(self):
        sprite = b'<svg><defs><path id="p" d="M1 1"/></defs><use href="#p" x="10"/></svg>'
        with self.assertRaises(SVGUnsupportedError):
            self.opt.optimize(sprite, self.cid, self.lic)

    def test_outline_strokes_are_not_silently_discarded(self):
        source = b'<svg><path d="M1 1 L2 2" fill="none" stroke="#000" stroke-width="2"/></svg>'
        with self.assertRaises(SVGUnsupportedError):
            self.opt.optimize(source, self.cid, self.lic)

    def test_roundtrip_rejects_changed_encoded_geometry_even_with_original_source_hash(self):
        svg = b'<svg viewBox="0 0 24 24"><path d="M1 1 L2 2" fill="#fff"/></svg>'
        packed = self.opt.optimize(svg, self.cid, self.lic)
        for field, wrong in (("e", []), ("pd", ["M4 4"])):
            with self.subTest(field=field):
                token = self.opt.decode(packed)
                token[field] = wrong
                tampered = zlib.compress(json.dumps(token, separators=(',', ':'), sort_keys=True).encode())
                with self.assertRaises(ValueError):
                    self.opt.verify_roundtrip(svg, tampered)

    def test_unsupported_elements(self):
        svg = b'<svg><text>Hello</text></svg>'
        with self.assertRaises(SVGUnsupportedError):
            self.opt.optimize(svg, self.cid, self.lic)

    def test_invalid_path(self):
        svg = b'<svg><path d="M0 0 invalid string X"/></svg>'
        with self.assertRaises(SVGParseError):
            self.opt.optimize(svg, self.cid, self.lic)

    def test_geometry_overflow(self):
        svg = b'<svg><circle cx="99999" cy="0" r="10"/></svg>'
        with self.assertRaises(SVGParseError):
            self.opt.optimize(svg, self.cid, self.lic)

    def test_external_references(self):
        svg = b'<svg><path fill="url(http://example.com/image.jpg)" d="M0 0"/></svg>'
        with self.assertRaises(SVGSecurityError):
            self.opt.optimize(svg, self.cid, self.lic)

        # Local refs should pass
        svg2 = b'<svg><path fill="url(#local)" d="M0 0"/></svg>'
        res = self.opt.optimize(svg2, self.cid, self.lic)
        self.assertIsNotNone(res)

    def test_nested_transforms(self):
        svg = b'<svg><g transform="translate(10, 10)"><path transform="scale(2)" d="M1 1 L2 2"/></g></svg>'
        res = self.opt.optimize(svg, self.cid, self.lic)
        token = self.opt.decode(res)

        self.assertEqual(token['e'][0]['tr'], "translate(10, 10) scale(2)")

    def test_quantization_and_deduplication(self):
        svg = b'<svg viewBox="0.000 0.000 24.1234 24.9876"><path d="M1.0001 1.00" fill="#fff"/><path d="M1.0001 1.00" fill="#fff"/></svg>'
        res = self.opt.optimize(svg, self.cid, self.lic)
        token = self.opt.decode(res)

        self.assertEqual(token['vb'], "0 0 24.12 24.99")
        self.assertEqual(len(token['p']), 1)
        self.assertEqual(len(token['pd']), 1)
        self.assertEqual(len(token['e']), 2)

    def test_size_limit(self):
        large_path = "".join([f"L{i} {i} " for i in range(1000)])
        svg = f'<svg><path d="M0 0 {large_path}"/></svg>'.encode()
        with self.assertRaises(SVGSizeError):
            self.opt.optimize(svg, self.cid, self.lic)

    def test_deterministic_output(self):
        svg = b'<svg viewBox="0 0 24 24"><path d="M1 1" fill="#fff"/></svg>'
        res1 = self.opt.optimize(svg, self.cid, self.lic)
        res2 = self.opt.optimize(svg, self.cid, self.lic)
        self.assertEqual(res1, res2)

    def test_roundtrip_verification(self):
        svg = b'<svg viewBox="0 0 24 24"><path d="M1 1 L2 2" fill="#fff"/></svg>'
        res = self.opt.optimize(svg, self.cid, self.lic)
        self.assertTrue(self.opt.verify_roundtrip(svg, res))

        # Test failure on corrupted hash
        token = self.opt.decode(res)
        token['src'] = "corrupted"
        corrupted_res = zlib.compress(json.dumps(token, separators=(',', ':'), sort_keys=True).encode('utf-8'))
        with self.assertRaises(ValueError):
            self.opt.verify_roundtrip(svg, corrupted_res)

        # Test failure on mismatched bounds
        svg_mismatch = b'<svg viewBox="0 0 100 100"><path d="M1 1 L2 2" fill="#fff"/></svg>'
        with self.assertRaises(ValueError):
            self.opt.verify_roundtrip(svg_mismatch, res)

if __name__ == '__main__':
    unittest.main()
