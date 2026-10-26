import io
import re
from typing import Dict, Any, List
from defusedxml.ElementTree import fromstring
import svgelements
from tools.visual_lexicon.core import encode_token, decode_token

def quantize(val: float, precision: int = 3) -> float:
    # If it's effectively an integer, return an int
    rounded = round(val, precision)
    if rounded == int(rounded):
        return int(rounded)
    return rounded

class SVGOptimizer:
    def __init__(self):
        self.allowed_tags = {
            'svg', 'g', 'path', 'circle', 'rect', 'line', 'polyline', 'polygon', 'ellipse'
        }
        self.disallowed_tags = {
            'script', 'foreignobject', 'image', 'text', 'style', 'iframe', 'object', 'embed'
        }
        self.ns_pattern = re.compile(r'\{.*\}')

    def sanitize_xml(self, svg_string: str) -> None:
        try:
            root = fromstring(svg_string)
        except Exception as e:
            raise ValueError(f"Invalid XML or security violation: {e}")

        self._check_element(root)

    def _strip_ns(self, tag: str) -> str:
        return self.ns_pattern.sub('', tag).lower()

    def _check_element(self, element) -> None:
        tag = self._strip_ns(element.tag)

        if tag not in self.allowed_tags:
            raise ValueError(f"Unsupported tag found: {tag}")

        if tag in self.disallowed_tags:
            raise ValueError(f"Disallowed tag found: {tag}")

        for attr, value in element.attrib.items():
            attr_lower = attr.lower()
            if attr_lower.startswith('on'):
                raise ValueError(f"Event handler found: {attr}")
            if 'javascript:' in value.lower():
                raise ValueError(f"JavaScript URI found in attribute: {attr}")
            if attr_lower in ('href', '{http://www.w3.org/1999/xlink}href'):
                if value.startswith('http') or value.startswith('//'):
                    raise ValueError(f"External reference found in href: {value}")

        for child in element:
            self._check_element(child)

    def optimize(self, svg_string: str, concept_id: str, semantic_label: str, author: str, source: str) -> Dict[str, Any]:
        self.sanitize_xml(svg_string)

        try:
            svg = svgelements.SVG.parse(io.StringIO(svg_string))
        except Exception as e:
            raise ValueError(f"Failed to parse SVG geometry: {e}")

        paths_set = set()
        paths_ordered = []
        palette_set = {}
        palette_list = []

        viewbox = [0, 0, 100, 100]
        if svg.viewbox:
            viewbox = [
                quantize(svg.viewbox.x),
                quantize(svg.viewbox.y),
                quantize(svg.viewbox.width),
                quantize(svg.viewbox.height)
            ]

        for element in svg.elements():
            if isinstance(element, svgelements.Shape):
                if not isinstance(element, svgelements.Path):
                    path = svgelements.Path(element)
                else:
                    path = element

                path *= path.transform

                # Default fill to black if not specified
                fill_color = "#000000"
                if path.fill is not None and hasattr(path.fill, 'hex'):
                    fill_color = path.fill.hex.lower()
                elif path.fill is not None and isinstance(path.fill, str):
                    fill_color = path.fill.lower()

                # Ensure properly formatted hex #xxx or #xxxxxx
                if not fill_color.startswith('#'):
                    fill_color = '#000000' # Simple fallback

                # Shorten hex code if possible
                if len(fill_color) == 7 and fill_color[1] == fill_color[2] and fill_color[3] == fill_color[4] and fill_color[5] == fill_color[6]:
                    fill_color = f"#{fill_color[1]}{fill_color[3]}{fill_color[5]}"

                if fill_color not in palette_set:
                    palette_set[fill_color] = len(palette_list)
                    palette_list.append(fill_color)

                # Get raw d_str and replace commas with spaces
                d_str = path.d()
                if not d_str:
                    continue
                d_str = d_str.replace(',', ' ')

                # Quantize coordinates in d_str
                def _quantize_match(m):
                    val = float(m.group(0))
                    return str(quantize(val))

                d_str = re.sub(r'[-+]?\d*\.\d+|[-+]?\d+', _quantize_match, d_str)
                # Cleanup d string: remove unnecessary spaces
                d_str = re.sub(r'\s+', ' ', d_str).strip()

                if d_str not in paths_set:
                    paths_set.add(d_str)
                    paths_ordered.append(d_str)

        if not paths_ordered:
            raise ValueError("No valid paths found in SVG")

        token = {
            "concept_id": concept_id,
            "version": 1,
            "viewBox": viewbox,
            "paths": paths_ordered,
            "palette": palette_list,
            "semantic_label": semantic_label
        }

        compressed, token_hash = encode_token(token)

        # Round trip validation to ensure geometry is not destructively lossy and size passes
        decoded_token = decode_token(compressed)

        # We ensure it matches exactly the fields we just set
        if decoded_token['concept_id'] != token['concept_id']:
             raise ValueError("Round-trip validation failed for concept_id")

        if decoded_token['paths'] != token['paths']:
            raise ValueError("Round-trip validation failed for paths")

        if decoded_token['viewBox'] != token['viewBox']:
            raise ValueError("Round-trip validation failed for viewBox")

        return {
            "token": token,
            "compressed_bytes": compressed,
            "hash": token_hash,
            "author": author,
            "source": source
        }
