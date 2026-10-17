import unittest
import zlib
import json
import random
from tools.svg_optimizer.optimizer import SVGOptimizer

class TestSVGOptimizer(unittest.TestCase):
    def setUp(self):
        self.optimizer = SVGOptimizer()

    def test_entity_expansion_attack(self):
        malicious_svg = b'''<?xml version="1.0"?>
        <!DOCTYPE lolz [
        <!ENTITY lol "lol">
        <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
        ]>
        <svg xmlns="http://www.w3.org/2000/svg">
            <text>&lol1;</text>
        </svg>'''
        with self.assertRaisesRegex(ValueError, "Unsafe SVG: DOCTYPE or ENTITY detected"):
            self.optimizer.optimize(malicious_svg, "test", "test_source", "hash")

        # Test UTF-16 bypass
        malicious_utf16 = malicious_svg.decode('utf-8').encode('utf-16')
        with self.assertRaisesRegex(ValueError, "Unsafe SVG: DOCTYPE or ENTITY detected"):
            self.optimizer.optimize(malicious_utf16, "test", "test_source", "hash")

    def test_unsafe_tags(self):
        svg_with_script = '''<svg xmlns="http://www.w3.org/2000/svg">
            <script>alert(1)</script>
            <path d="M 0 0 L 1 1"/>
        </svg>'''
        with self.assertRaisesRegex(ValueError, "Unsafe SVG: <script> element not allowed"):
            self.optimizer.optimize(svg_with_script, "test", "test_source", "hash")

        svg_with_foreignObject = '''<svg xmlns="http://www.w3.org/2000/svg">
            <foreignObject width="100" height="100">
                <body xmlns="http://www.w3.org/1999/xhtml">
                    <p>Some text</p>
                </body>
            </foreignObject>
        </svg>'''
        with self.assertRaisesRegex(ValueError, "Unsafe SVG: <foreignObject> element not allowed"):
            self.optimizer.optimize(svg_with_foreignObject, "test", "test_source", "hash")

        svg_with_unsupported = '''<svg xmlns="http://www.w3.org/2000/svg">
            <line x1="0" y1="0" x2="1" y2="1"/>
        </svg>'''
        with self.assertRaisesRegex(ValueError, "Unsupported geometry tag: <line>"):
            self.optimizer.optimize(svg_with_unsupported, "test", "test_source", "hash")

        svg_with_transform = '''<svg xmlns="http://www.w3.org/2000/svg">
            <path d="M 0 0 L 1 1" transform="scale(2)"/>
        </svg>'''
        with self.assertRaisesRegex(ValueError, "Unsafe SVG: Transforms are not supported by the normalizer yet."):
            self.optimizer.optimize(svg_with_transform, "test", "test_source", "hash")

    def test_event_handlers(self):
        svg_with_event = '''<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">
            <path d="M 0 0 L 1 1"/>
        </svg>'''
        with self.assertRaisesRegex(ValueError, "Unsafe SVG: Event handler 'onload' not allowed"):
            self.optimizer.optimize(svg_with_event, "test", "test_source", "hash")

    def test_network_references(self):
        svg_with_http = '''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
            <use xlink:href="http://example.com/icon.svg#icon"/>
        </svg>'''
        with self.assertRaisesRegex(ValueError, "Unsupported geometry tag: <use>"):
            self.optimizer.optimize(svg_with_http, "test", "test_source", "hash")

        svg_with_url = '''<svg xmlns="http://www.w3.org/2000/svg">
            <path d="M 0 0 L 1 1" fill="url(https://example.com/grad.svg#grad)"/>
        </svg>'''
        with self.assertRaisesRegex(ValueError, r"Unsafe SVG: External reference in url\(\) 'url\(https://example.com/grad.svg#grad\)' not allowed"):
            self.optimizer.optimize(svg_with_url, "test", "test_source", "hash")

    def test_geometry_deduplication_and_quantization(self):
        svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
            <path d="M 1.0001 2.0009 L 3.5 4.5"/>
            <path d="M   1.0   2.0 L 3.5 4.5  "/>
        </svg>'''

        # Test extraction directly to verify path properties
        root = self.optimizer.parse_secure(svg)
        paths, palette, viewBox = self.optimizer.validate_and_extract(root)

        # Should be deduplicated and quantized to M 1 2 L 3.5 4.5
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0], "M 1 2 L 3.5 4.5")

    def test_determinism(self):
        svg1 = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
            <path d="M 1 2 L 3 4" fill="#ff0000"/>
            <path d="M 5 6 L 7 8" fill="#00ff00"/>
        </svg>'''

        svg2 = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
            <path d="M 5 6 L 7 8" fill="#00ff00"/>
            <path d="M 1 2 L 3 4" fill="#ff0000"/>
        </svg>'''

        token1 = self.optimizer.optimize(svg1, "test_label", "evidence", "hash")
        token2 = self.optimizer.optimize(svg2, "test_label", "evidence", "hash")

        self.assertEqual(token1, token2)

    def test_round_trip_and_size_limit(self):
        # Create a massive SVG to trigger size limit (use random paths so zlib doesn't compress it to nothing)
        huge_path = " ".join([f"M {random.randint(0, 100)} {random.randint(0, 100)} L {random.randint(0, 100)} {random.randint(0, 100)}" for _ in range(500)])
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
            <path d="{huge_path}"/>
        </svg>'''

        with self.assertRaisesRegex(ValueError, "Compressed token exceeds 2048 bytes"):
            self.optimizer.optimize(svg, "huge_label", "huge_evidence", "hash")

        # Test successful encoding round-trip logic check
        valid_svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
            <path d="M 1 2 L 3 4"/>
            <rect x="0" y="0" width="10" height="10"/>
        </svg>'''
        token = self.optimizer.optimize(valid_svg, "valid_label", "evidence", "hash")

        # Decompress token and verify data
        json_bytes = zlib.decompress(token)
        data = json.loads(json_bytes)

        self.assertEqual(data["version"], "J053")
        self.assertEqual(data["viewBox"], "0 0 24 24")
        self.assertIn("M 1 2 L 3 4", data["paths"])
        # Checking rect extraction (M 0.0 0.0 h 10.0 v 10.0 h -10.0 Z -> M 0 0 h 10 v 10 h -10 Z)
        self.assertIn("M 0 0 h 10 v 10 h -10 Z", data["paths"])
        self.assertEqual(data["semantic_label"], "valid_label")
        self.assertEqual(data["source_evidence"], "evidence")
        self.assertEqual(data["source_hash"], "hash")
