import xml.etree.ElementTree as ET
import json
import zlib
import re
import hashlib
from typing import Dict, List, Any
from tools.visual_lexicon.core import encode_token, decode_token
from tools.visual_lexicon.schema import HEX_COLOR

class SVGSecurityError(ValueError): pass
class SVGUnsupportedError(ValueError): pass
class SVGParseError(ValueError): pass
class SVGSizeError(ValueError): pass

ALLOWED_ELEMENTS = {
    'svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon', 'defs', 'use', 'title', 'desc'
}

def quantize_numbers(s: str, precision: int = 2) -> str:
    if not s: return s
    def repl(m):
        val = float(m.group(0))
        if abs(val) > 10000:
            raise SVGParseError("Geometry overflow detected in path or transform")
        q = f"{val:.{precision}f}".rstrip('0').rstrip('.')
        if q == '-0': q = '0'
        if q == '': q = '0'
        return q
    return re.sub(r'[-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?', repl, s)

def check_security(xml_bytes: bytes):
    # Detect UTF-16 before trying UTF-8: BOM-less UTF-16 contains valid
    # ASCII bytes interleaved with NULs, hiding dangerous XML declarations.
    try:
        if xml_bytes.startswith((b'\xff\xfe', b'\xfe\xff')):
            decoded = xml_bytes.decode('utf-16')
        elif xml_bytes.startswith(b'<\x00'):
            decoded = xml_bytes.decode('utf-16le')
        elif xml_bytes.startswith(b'\x00<'):
            decoded = xml_bytes.decode('utf-16be')
        else:
            decoded = xml_bytes.decode('utf-8')
    except UnicodeError as exc:
        raise SVGSecurityError("Unsupported or malformed XML encoding") from exc
    if '\x00' in decoded:
        raise SVGSecurityError("NUL bytes or invalid encoding in SVG")

    upper_str = decoded.upper()

    # More robust checks replacing the simple byte checks
    if re.search(r'<!DOCTYPE', upper_str) or re.search(r'<!ENTITY', upper_str):
        raise SVGSecurityError("DTDs and Entities are disabled for security")
    if re.search(r'<SCRIPT', upper_str) or re.search(r'JAVASCRIPT:', upper_str):
        raise SVGSecurityError("Scripts and JS execution are forbidden")
    if re.search(r'<FOREIGNOBJECT', upper_str):
        raise SVGSecurityError("foreignObject is forbidden")
    if re.search(r'<IMAGE', upper_str):
        raise SVGSecurityError("Remote images are forbidden")
    if re.search(r'<IFRAME', upper_str) or re.search(r'<OBJECT', upper_str):
        raise SVGSecurityError("External objects are forbidden")

class SVGOptimizer:
    def __init__(self, precision: int = 2):
        self.precision = precision

    def optimize(self, svg_bytes: bytes, concept_id: str, license_evidence: str) -> bytes:
        check_security(svg_bytes)
        try:
            parser = ET.XMLParser()
            root = ET.fromstring(svg_bytes, parser=parser)
        except ET.ParseError as e:
            raise SVGParseError(f"Invalid XML: {e}")

        source_hash = hashlib.sha256(svg_bytes).hexdigest()

        viewBox = root.attrib.get('viewBox')
        if viewBox:
            vb_str = quantize_numbers(viewBox, self.precision)
            viewBox_list = [float(x) for x in vb_str.replace(',', ' ').split()]
        else:
            w = root.attrib.get('width', '24')
            h = root.attrib.get('height', '24')
            vb_str = f"0 0 {quantize_numbers(w, self.precision)} {quantize_numbers(h, self.precision)}"
            viewBox_list = [float(x) for x in vb_str.replace(',', ' ').split()]

        semantic_label = concept_id[:100]
        title_el = root.find('.//{*}title')
        if title_el is not None and title_el.text:
            semantic_label = title_el.text.strip()[:100]
        else:
            desc_el = root.find('.//{*}desc')
            if desc_el is not None and desc_el.text:
                semantic_label = desc_el.text.strip()[:100]

        if not semantic_label:
            semantic_label = concept_id[:100]

        elements = []
        palette = {}
        palette_list = []
        path_data_map = {}
        path_data_list = []

        def get_color_index(color: str):
            if not color: return None
            if not HEX_COLOR.fullmatch(color):
                if color.startswith('url(#'):
                    # For local references, they are unsupported by J053 palette. We should probably raise SVGUnsupportedError.
                    raise SVGUnsupportedError(f"Unsupported local reference fill: {color}")
                raise SVGParseError(f"Invalid hex color: {color}")
            if color not in palette:
                palette[color] = len(palette_list)
                palette_list.append(color)
            return palette[color]

        def get_path_index(d: str):
            if not d: return None

            # Simple path validation
            if not re.match(r'^[MmLlHhVvCcSsQqTtAaZz0-9\s,\.-]+$', d):
                raise SVGParseError(f"Invalid characters in path data: {d}")

            if d not in path_data_map:
                path_data_map[d] = len(path_data_list)
                path_data_list.append(d)
            return path_data_map[d]

        def process_element(node, current_fill=None, current_transform=None):
            tag = node.tag.split('}')[-1]
            if tag not in ALLOWED_ELEMENTS:
                if tag in ('script', 'foreignObject', 'image', 'style', 'iframe', 'object'):
                    raise SVGSecurityError(f"Forbidden element: {tag}")
                raise SVGUnsupportedError(f"Unsupported element: {tag}")
            # This compact-vector format does not model definitions or <use>
            # references. Reject rather than silently dropping sprite geometry.
            if tag in ('defs', 'use'):
                raise SVGUnsupportedError("defs/use geometry is not representable")

            for attr, val in node.attrib.items():
                if attr.lower().startswith('on'):
                    raise SVGSecurityError(f"Event handlers are forbidden: {attr}")
                if re.search(r'url\s*\(', val, re.IGNORECASE):
                    # CSS function names are case-insensitive; only local IDs
                    # may be retained by the current token format.
                    if not re.fullmatch(r'url\s*\(\s*\#[A-Za-z0-9_.:-]+\s*\)',
                                        val.strip(), re.IGNORECASE):
                        raise SVGSecurityError("External references are forbidden")
                key = attr.split('}')[-1].lower()
                if key == 'style':
                    raise SVGUnsupportedError("CSS presentation is not representable")
                if key == 'stroke' and val.strip().lower() != 'none':
                    raise SVGUnsupportedError("Stroked geometry is not representable")
                if key in ('stroke-width', 'stroke-linecap', 'stroke-linejoin',
                           'stroke-dasharray', 'stroke-dashoffset'):
                    raise SVGUnsupportedError("Stroke presentation is not representable")

            fill = node.attrib.get('fill', current_fill)
            transform = node.attrib.get('transform')

            if transform:
                transform = quantize_numbers(transform, self.precision)
                if current_transform:
                    transform = current_transform + " " + transform
            else:
                transform = current_transform

            if tag in ('path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon'):
                el_data = {'t': tag}
                c_idx = get_color_index(fill)
                if c_idx is not None:
                    el_data['f'] = c_idx
                if transform:
                    el_data['tr'] = transform

                for attr in ['d', 'x', 'y', 'width', 'height', 'cx', 'cy', 'r', 'rx', 'ry', 'x1', 'y1', 'x2', 'y2', 'points']:
                    if attr in node.attrib:
                        val = quantize_numbers(node.attrib[attr], self.precision)
                        if attr == 'd':
                            el_data['d'] = get_path_index(val)
                        else:
                            # Geometry overflow check for simple numeric attributes
                            try:
                                if ' ' in val or ',' in val:
                                    # Very basic check for arrays like points
                                    nums = [float(x) for x in val.replace(',', ' ').split()]
                                    if any(abs(n) > 10000 for n in nums):
                                        raise SVGParseError("Geometry overflow detected")
                                else:
                                    if abs(float(val)) > 10000:
                                        raise SVGParseError("Geometry overflow detected")
                            except ValueError:
                                pass

                            el_data[attr] = val

                elements.append(el_data)

            for child in node:
                process_element(child, fill, transform)

        process_element(root)

        token = {
            "version": 1,
            "concept_id": concept_id,
            "license": license_evidence,
            "source": source_hash,
            "viewBox": viewBox_list,
            "palette": palette_list,
            "paths": path_data_list,
            "elements": elements,
            "semantic_label": semantic_label
        }

        try:
            compressed, token_hash = encode_token(token)
        except ValueError as e:
            if "too large" in str(e).lower():
                raise SVGSizeError(str(e))
            raise SVGParseError(f"Token encoding failed: {e}")

        return compressed

    def decode(self, compressed_bytes: bytes) -> dict:
        return decode_token(compressed_bytes)

    def verify_roundtrip(self, original_svg: bytes, compressed_bytes: bytes):
        token = self.decode(compressed_bytes)

        # 1. Source Hash Verification
        if token.get('source') != hashlib.sha256(original_svg).hexdigest():
            raise ValueError("Source hash mismatch in roundtrip")

        # 2. Deterministic Encoding Verification
        re_encoded, _ = encode_token(token)
        if re_encoded != compressed_bytes:
            raise ValueError("Deterministic encoding failed in roundtrip")

        # 3. Geometry and Visual-Bounds Verifier
        parser = ET.XMLParser()
        try:
            root = ET.fromstring(original_svg, parser=parser)
        except ET.ParseError:
            raise ValueError("Original SVG could not be parsed for geometry verification")

        orig_viewBox = root.attrib.get('viewBox')
        if orig_viewBox:
            orig_vb_str = quantize_numbers(orig_viewBox, self.precision)
            orig_viewBox_list = [float(x) for x in orig_vb_str.replace(',', ' ').split()]
        else:
            w = root.attrib.get('width', '24')
            h = root.attrib.get('height', '24')
            orig_vb_str = f"0 0 {quantize_numbers(w, self.precision)} {quantize_numbers(h, self.precision)}"
            orig_viewBox_list = [float(x) for x in orig_vb_str.replace(',', ' ').split()]

        if token.get('viewBox') != orig_viewBox_list:
            raise ValueError(f"ViewBox bounds mismatch in roundtrip: {token.get('viewBox')} != {orig_viewBox_list}")

        # Rebuild the independently parsed source geometry. A matching 'source'
        # hash and viewBox alone cannot prove that palette, shapes or paths
        # survived the encoding round trip intact.
        try:
            expected = self.decode(self.optimize(original_svg, token['concept_id'], token['license']))
        except (KeyError, TypeError, SVGParseError, SVGUnsupportedError,
                SVGSecurityError, SVGSizeError, ValueError) as exc:
            raise ValueError("Unverifiable source geometry") from exc
        for key in ('viewBox', 'palette', 'paths', 'elements', 'semantic_label'):
            if token.get(key) != expected.get(key):
                raise ValueError(f"Encoded geometry mismatch in roundtrip: {key}")

        return True
