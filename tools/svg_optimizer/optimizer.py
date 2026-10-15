import xml.etree.ElementTree as ET
import zlib
import json
import re
from typing import Dict, Any, List

class SVGOptimizer:
    def __init__(self):
        self.allowed_elements = {'svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon'}
        self.ignored_elements = {'title', 'desc', 'metadata', 'style', 'defs'}
        self.max_size = 2048

    def optimize(self, svg_content: str, concept_id: str, license_evidence: str, source_hash: str) -> bytes:
        if "<!DOCTYPE" in svg_content.upper() or "<!ENTITY" in svg_content.upper():
            raise ValueError("Unsafe SVG: DOCTYPE/ENTITY not allowed.")

        try:
            parser = ET.XMLParser()
            if hasattr(parser, 'entity'):
                parser.entity.clear()
            root = ET.fromstring(svg_content, parser=parser)
        except ET.ParseError as e:
            raise ValueError(f"Invalid SVG: {e}")

        geometry = self._process_element(root)

        # Deduplicate palette and paths
        palette = {}
        paths = {}
        final_geom = []
        for elem in geometry:
            new_elem = {}
            for k, v in elem.items():
                if k in ('fill', 'stroke'):
                    v_norm = v.lower() if v.startswith('#') else v
                    if v_norm not in palette:
                        palette[v_norm] = str(len(palette))
                    new_elem[k] = palette[v_norm]
                elif k in ('d', 'points'):
                    if v not in paths:
                        paths[v] = str(len(paths))
                    new_elem[k] = paths[v]
                else:
                    new_elem[k] = v
            final_geom.append(new_elem)

        token = {
            "c": concept_id,
            "l": license_evidence,
            "h": source_hash,
            "p": {str(v): k for k, v in palette.items()},
            "d": {str(v): k for k, v in paths.items()},
            "g": final_geom
        }

        token_str = json.dumps(token, separators=(',', ':'), sort_keys=True)
        compressed = zlib.compress(token_str.encode('utf-8'))

        if len(compressed) > self.max_size:
            raise ValueError(f"Compressed token exceeds {self.max_size} bytes limit.")

        return compressed

    def _process_element(self, element: ET.Element, parent_attrs: Dict[str, str] = None) -> List[Dict[str, Any]]:
        tag = element.tag.split('}')[-1]

        if tag in self.ignored_elements:
            return []

        if tag not in self.allowed_elements:
            raise ValueError(f"Unsupported SVG element: {tag}")

        for attr, value in element.attrib.items():
            clean_attr = attr.split('}')[-1]
            if clean_attr.startswith('on'):
                raise ValueError("Unsafe SVG: Event handlers not allowed.")
            if 'http://' in value or 'https://' in value:
                raise ValueError("Unsafe SVG: Network references not allowed.")

        geom = []
        node_data = {"t": tag}

        combined_attrs = {}
        if parent_attrs:
            combined_attrs.update(parent_attrs)

        for attr, value in element.attrib.items():
            clean_attr = attr.split('}')[-1]
            if clean_attr == 'style':
                for rule in value.split(';'):
                    if ':' in rule:
                        k, v = rule.split(':', 1)
                        k, v = k.strip(), v.strip()
                        if k in ('fill', 'stroke', 'stroke-width'):
                            combined_attrs[k] = self._quantize_numbers(v) if k == 'stroke-width' else v
            elif clean_attr in ('d', 'points', 'x', 'y', 'width', 'height', 'cx', 'cy', 'r', 'rx', 'ry', 'x1', 'y1', 'x2', 'y2', 'stroke-width'):
                combined_attrs[clean_attr] = self._quantize_numbers(value)
            elif clean_attr in ('fill', 'stroke', 'transform', 'viewBox'):
                # For transform, if parent has transform, combine them
                if clean_attr == 'transform' and 'transform' in combined_attrs:
                    combined_attrs[clean_attr] = combined_attrs['transform'] + " " + self._quantize_numbers(value)
                else:
                    combined_attrs[clean_attr] = self._quantize_numbers(value) if clean_attr in ('transform', 'viewBox') else value

        for k, v in combined_attrs.items():
            node_data[k] = v

        if tag != 'g' and tag != 'svg':
            # For shapes, only extract relevant attributes to avoid bloat from parent
            filtered_node = {"t": tag}
            for k in ('d', 'points', 'x', 'y', 'width', 'height', 'cx', 'cy', 'r', 'rx', 'ry', 'x1', 'y1', 'x2', 'y2', 'fill', 'stroke', 'stroke-width', 'transform'):
                if k in node_data:
                    filtered_node[k] = node_data[k]
            # Validate path/points depending on element
            if tag == 'path' and 'd' not in filtered_node:
                raise ValueError("Invalid path: missing 'd' attribute")
            if tag in ('polygon', 'polyline') and 'points' not in filtered_node:
                raise ValueError(f"Invalid {tag}: missing 'points' attribute")
            geom.append(filtered_node)
        elif tag == 'svg' and 'viewBox' in node_data:
            geom.append({"t": "viewBox", "v": node_data["viewBox"]})

        # Passing down inheritable properties to children
        inheritable = {}
        for k in ('fill', 'stroke', 'stroke-width', 'transform'):
            if k in node_data:
                inheritable[k] = node_data[k]

        for child in element:
            geom.extend(self._process_element(child, inheritable))

        return geom

    def _quantize_numbers(self, data: str) -> str:
        def round_num(match):
            val = float(match.group(0))
            if val == 0: return "0"
            res = f"{val:.3f}".rstrip('0').rstrip('.')
            if res == "-0": return "0"
            return res

        return re.sub(r'[-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?', round_num, data)

    def verify_bounds(self, svg_content: str, token_bytes: bytes) -> bool:
        decompressed = zlib.decompress(token_bytes).decode('utf-8')
        token = json.loads(decompressed)

        try:
            root = ET.fromstring(svg_content)
        except ET.ParseError:
            return False

        svg_viewbox = root.attrib.get('viewBox', '')
        if svg_viewbox:
            svg_viewbox = self._quantize_numbers(svg_viewbox)

        token_viewbox = ""
        for g in token.get('g', []):
            if g.get('t') == 'viewBox':
                token_viewbox = g.get('v', '')
                break

        if svg_viewbox and svg_viewbox != token_viewbox:
            return False

        try:
            new_token_bytes = self.optimize(svg_content, token['c'], token['l'], token['h'])
            if new_token_bytes != token_bytes:
                return False
        except Exception:
            return False

        return True
