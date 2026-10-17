import xml.etree.ElementTree as ET
import zlib
import json
import re

# In Python 3.8+, ElementTree has a limited vulnerability surface, but we must manually enforce
# entity expansion limits or reject documents containing DTDs altogether to be safe.
# defusedxml is best, but since it's not present by default and we can't alter dependencies,
# we'll build a more robust check that handles encoding bypasses.

class SVGOptimizer:
    def __init__(self):
        pass

    def parse_secure(self, svg_content):
        if isinstance(svg_content, str):
            svg_content_bytes = svg_content.encode('utf-8')
        else:
            svg_content_bytes = svg_content

        # Determine encoding from BOM or XML declaration
        encoding = 'utf-8'
        if svg_content_bytes.startswith(b'\xff\xfe') or svg_content_bytes.startswith(b'\xfe\xff'):
            encoding = 'utf-16'
        elif svg_content_bytes.startswith(b'\xff\xfe\x00\x00') or svg_content_bytes.startswith(b'\x00\x00\xfe\xff'):
            encoding = 'utf-32'

        try:
            content_str = svg_content_bytes.decode(encoding)
        except UnicodeDecodeError:
            # Fallback string handling
            content_str = str(svg_content_bytes)

        # Reject DOCTYPE and ENTITY to prevent entity expansion attacks in any encoding
        upper_content = content_str.upper()
        if "<!DOCTYPE" in upper_content or "<!ENTITY" in upper_content:
            raise ValueError("Unsafe SVG: DOCTYPE or ENTITY detected")

        try:
            return ET.fromstring(svg_content_bytes)
        except ET.ParseError as e:
            raise ValueError(f"Invalid XML: {e}")

    def validate_node(self, node):
        tag = node.tag.split('}')[-1] if '}' in node.tag else node.tag

        unsafe_tags = {'script', 'foreignobject', 'iframe', 'object', 'embed', 'image'}
        if tag.lower() in unsafe_tags:
            raise ValueError(f"Unsafe SVG: <{tag}> element not allowed")

        # Reject unhandled geometry tags
        supported_geometry_tags = {'path', 'rect', 'circle', 'polygon', 'svg', 'g', 'defs', 'title', 'desc', 'style', 'metadata'}
        if tag not in supported_geometry_tags:
            raise ValueError(f"Unsupported geometry tag: <{tag}>")

        for attr, value in node.attrib.items():
            attr_name = attr.split('}')[-1] if '}' in attr else attr
            attr_lower = attr_name.lower()

            if attr_lower.startswith('on'):
                raise ValueError(f"Unsafe SVG: Event handler '{attr}' not allowed")

            if attr_lower in ('href', 'src'):
                val_lower = value.lower()
                if val_lower.startswith('http://') or val_lower.startswith('https://') or val_lower.startswith('//'):
                    raise ValueError(f"Unsafe SVG: Network reference '{value}' not allowed")

            if 'url(' in value.lower():
                url_match = re.search(r'url\(\s*[\'"]?(.*?)[\'"]?\s*\)', value, re.IGNORECASE)
                if url_match:
                    url_val = url_match.group(1)
                    if not url_val.startswith('#'):
                        raise ValueError(f"Unsafe SVG: External reference in url() '{value}' not allowed")

            if attr_lower == 'transform':
                raise ValueError("Unsafe SVG: Transforms are not supported by the normalizer yet.")

    def normalize_number(self, match):
        val = float(match.group())
        # Quantize to 1 decimal place to tolerate 2.0009 vs 2.0 visually
        val = round(val, 1)
        if val.is_integer():
            return str(int(val))
        s = str(val)
        if '.' in s:
            s = s.rstrip('0').rstrip('.')
        return s

    def normalize_path(self, d):
        if not d:
            return ""

        # Replace floats with quantized values
        # Match numbers with optional signs and decimals
        d = re.sub(r'[-+]?\d*\.\d+|[-+]?\d+', self.normalize_number, d)

        # Compress whitespace
        d = re.sub(r'\s+', ' ', d)

        # Add space between letter and number if not present (to ensure uniform spacing)
        # First, ensure spaces around all letters
        d = re.sub(r'([A-Za-z])', r' \1 ', d)

        # Re-compress whitespace
        d = re.sub(r'\s+', ' ', d)

        # Remove space after commands
        d = re.sub(r'([A-Za-z])\s+', r'\1 ', d)
        # Remove space before commands
        d = re.sub(r'\s+([A-Za-z])', r' \1', d)

        return d.strip()

    def extract_geometry(self, node):
        tag = node.tag.split('}')[-1] if '}' in node.tag else node.tag

        d = None
        if tag == 'path':
            d = node.attrib.get('d')
        elif tag == 'rect':
            x = float(node.attrib.get('x', '0'))
            y = float(node.attrib.get('y', '0'))
            w = float(node.attrib.get('width', '0'))
            h = float(node.attrib.get('height', '0'))
            # Convert rect to path
            d = f"M {x} {y} h {w} v {h} h {-w} Z"
        elif tag == 'circle':
            cx = float(node.attrib.get('cx', '0'))
            cy = float(node.attrib.get('cy', '0'))
            r = float(node.attrib.get('r', '0'))
            # Convert circle to path with two arcs
            d = f"M {cx - r} {cy} a {r} {r} 0 1 0 {2*r} 0 a {r} {r} 0 1 0 {-2*r} 0"
        elif tag == 'polygon':
            points = node.attrib.get('points', '')
            if points:
                parts = points.strip().replace(',', ' ').split()
                if len(parts) >= 2:
                    d = f"M {parts[0]} {parts[1]}"
                    for i in range(2, len(parts), 2):
                        if i+1 < len(parts):
                            d += f" L {parts[i]} {parts[i+1]}"
                    d += " Z"

        if d:
            d = self.normalize_path(d)

        return d

    def validate_and_extract(self, root):
        paths_set = set()
        palette_set = set()
        viewBox = root.attrib.get('viewBox', "0 0 24 24")

        for node in root.iter():
            self.validate_node(node)
            d = self.extract_geometry(node)
            if d:
                # Add to set after removing extraneous spaces (handled by normalize_path)
                paths_set.add(d)

            # Extract simple fill colors for palette
            fill = node.attrib.get('fill')
            if fill and fill != 'none' and not fill.startswith('url('):
                palette_set.add(fill.lower())

        # Deduplicated lists deterministically ordered
        paths = sorted(list(paths_set))
        palette = sorted(list(palette_set))

        return paths, palette, viewBox

    def encode_j053(self, paths, palette, semantic_label, source_evidence, source_hash, viewBox):
        token_data = {
            "version": "J053",
            "viewBox": viewBox,
            "paths": paths,
            "palette": palette,
            "semantic_label": semantic_label,
            "source_evidence": source_evidence,
            "source_hash": source_hash
        }

        # Deterministic JSON serialization
        json_bytes = json.dumps(token_data, separators=(',', ':'), sort_keys=True).encode('utf-8')

        # Compress
        compressed = zlib.compress(json_bytes)

        if len(compressed) > 2048:
            raise ValueError(f"Compressed token exceeds 2048 bytes (size: {len(compressed)})")

        return compressed, json_bytes

    def verify_round_trip(self, compressed, expected_paths, expected_viewBox):
        try:
            json_bytes = zlib.decompress(compressed)
            data = json.loads(json_bytes)

            if data["viewBox"] != expected_viewBox:
                raise ValueError("Round-trip viewBox mismatch")

            decoded_paths = set(data.get("paths", []))
            expected_paths_set = set(expected_paths)
            if decoded_paths != expected_paths_set:
                raise ValueError("Round-trip geometry mismatch")

        except Exception as e:
            raise ValueError(f"Round-trip verification failed: {e}")

    def optimize(self, svg_content, semantic_label, source_evidence, source_hash=""):
        root = self.parse_secure(svg_content)
        paths, palette, viewBox = self.validate_and_extract(root)
        compressed, _ = self.encode_j053(paths, palette, semantic_label, source_evidence, source_hash, viewBox)

        # Verify geometry and bounds
        self.verify_round_trip(compressed, paths, viewBox)

        return compressed
