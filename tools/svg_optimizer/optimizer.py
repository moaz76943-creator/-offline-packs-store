import re
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Tuple
import zlib
import hashlib
import json

from tools.svg_optimizer.verifier import verify_geometry, verify_arc_radii, verify_size_bounds

try:
    from tools.visual_lexicon.core import encode_token
except ImportError:
    def encode_token(token):
        serialized = json.dumps(token, separators=(',', ':'), sort_keys=True).encode('utf-8')
        return zlib.compress(serialized, level=9), hashlib.sha256(serialized).hexdigest()

def tokenize_path(path_str: str) -> List[tuple]:
    tokens = re.findall(r'([a-zA-Z])|(-?\d+(?:\.\d+)?(?:[eE]-?\d+)?)', path_str)
    commands = []
    current_cmd = None
    args = []

    for char, num in tokens:
        if char:
            if current_cmd:
                commands.append((current_cmd, args))
            current_cmd = char
            args = []
        elif num:
            args.append(float(num))

    if current_cmd:
        commands.append((current_cmd, args))

    return commands

def serialize_path(commands: List[tuple]) -> str:
    parts = []
    for cmd, args in commands:
        parts.append(cmd)
        str_args = [f"{round(a, 3):g}" for a in args]
        if str_args:
            parts.append(" ".join(str_args))
    return " ".join(parts)

class SvgOptimizer:
    def __init__(self):
        self.forbidden_tags = {'script', 'foreignObject', 'use', 'text', 'image', 'style', 'rect', 'circle', 'ellipse', 'polygon', 'polyline'}
        self.forbidden_attrs = {'stroke', 'style', 'rotate'}

    def parse_securely(self, svg_string: str) -> ET.Element:
        """
        Parses an SVG string securely. Prevents DOCTYPE and ENTITY declarations to mitigate attacks.
        """
        if re.search(r'<!DOCTYPE', svg_string, re.IGNORECASE):
            raise ValueError("DOCTYPE declarations are not allowed")
        if re.search(r'<!ENTITY', svg_string, re.IGNORECASE):
            raise ValueError("ENTITY declarations are not allowed")

        # Using ET to parse which by default doesn't resolve external entities.
        try:
            root = ET.fromstring(svg_string)
        except ET.ParseError as e:
            raise ValueError(f"Invalid XML: {e}")

        self._check_element(root)
        return root

    def _check_element(self, element: ET.Element):
        tag = element.tag.split('}')[-1] if '}' in element.tag else element.tag

        if tag in self.forbidden_tags:
            raise ValueError(f"Forbidden element <{tag}> found in SVG")

        for attr, value in element.attrib.items():
            attr_name = attr.split('}')[-1] if '}' in attr else attr
            if attr_name in self.forbidden_attrs:
                raise ValueError(f"Forbidden attribute '{attr_name}' found on <{tag}>")
            if attr_name.startswith('on'):
                raise ValueError(f"Event handler attribute '{attr_name}' found on <{tag}>")
            if attr_name in ('href', 'xlink:href') and (value.startswith('http://') or value.startswith('https://') or value.startswith('//')):
                raise ValueError(f"Remote reference found in '{attr_name}'")

        for child in element:
            self._check_element(child)

    def optimize_to_token(self, svg_string: str, metadata: Dict[str, Any]) -> Tuple[bytes, str]:
        root = self.parse_securely(svg_string)

        view_box_str = root.attrib.get('viewBox')
        if not view_box_str:
            raise ValueError("viewBox is required on the root <svg> element")

        vb_parts = [float(x) for x in re.split(r'[,\s]+', view_box_str.strip()) if x]
        if len(vb_parts) != 4:
            raise ValueError("viewBox must have exactly 4 numbers")

        paths = []
        palette = set()

        def _process_node(node: ET.Element):
            tag = node.tag.split('}')[-1] if '}' in node.tag else node.tag

            if 'transform' in node.attrib:
                raise ValueError("Nested transforms are restricted (requires flattened geometry)")

            if tag == 'path':
                d = node.attrib.get('d', '')
                if not d:
                    return
                cmds = tokenize_path(d)
                for cmd, _ in cmds:
                    if cmd.islower() and cmd != 'z':
                        raise ValueError(f"Relative path command '{cmd}' is not allowed in strict subset")
                d = serialize_path(cmds)
                paths.append(d)

                fill = node.attrib.get('fill')
                if fill and fill != 'none':
                    if re.match(r'^#[0-9a-fA-F]{3,6}$', fill):
                        if len(fill) == 4:
                            fill = '#' + fill[1]*2 + fill[2]*2 + fill[3]*2
                        palette.add(fill.lower())

            elif tag == 'line':
                x1 = node.attrib.get('x1', '0')
                y1 = node.attrib.get('y1', '0')
                x2 = node.attrib.get('x2', '0')
                y2 = node.attrib.get('y2', '0')
                d = f"M {float(x1):g} {float(y1):g} L {float(x2):g} {float(y2):g}"
                paths.append(d)

                fill = node.attrib.get('fill')
                if fill and fill != 'none':
                    if re.match(r'^#[0-9a-fA-F]{3,6}$', fill):
                        if len(fill) == 4:
                            fill = '#' + fill[1]*2 + fill[2]*2 + fill[3]*2
                        palette.add(fill.lower())

            for child in node:
                _process_node(child)

        _process_node(root)

        unique_paths = list(dict.fromkeys(paths))

        # Verify Geometry Limits and Radii
        verify_geometry(unique_paths, vb_parts)
        verify_arc_radii(unique_paths)

        token = {
            'concept_id': metadata.get('concept_id'),
            'version': metadata.get('version', 1),
            'viewBox': vb_parts,
            'paths': unique_paths,
            'palette': sorted(list(palette)),
            'semantic_label': metadata.get('semantic_label'),
            'author': metadata.get('author'),
            'source': metadata.get('source'),
            'license': metadata.get('license')
        }

        token = {k: v for k, v in token.items() if v is not None}

        # Encode token and verify size
        token_bytes, token_hash = encode_token(token)
        verify_size_bounds(token_bytes)

        return token_bytes, token_hash
