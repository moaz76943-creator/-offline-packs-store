import xml.etree.ElementTree as ET
import re
from typing import Dict, Any, List, Tuple
import math
from tools.visual_lexicon.core import encode_token
from tools.svg_optimizer.verifier import verify_geometry_roundtrip

class SvgOptimizer:
    def __init__(self):
        # Reject DTD and ENTITY to prevent XXE / Billion Laughs attacks
        self.unsafe_pattern = re.compile(r'<!DOCTYPE|<!ENTITY', re.IGNORECASE)
        self.supported_elements = {'svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'polygon', 'polyline', 'line', 'defs'}
        self.rejected_elements = {'script', 'foreignObject', 'text', 'use', 'image', 'style'}
        self.rejected_attrs = {'stroke', 'style'}
        self.quantize_digits = 2

    def _parse_transform(self, transform_str: str) -> List[Tuple[float, float, float, float, float, float]]:
        if not transform_str:
            return [(1, 0, 0, 1, 0, 0)]

        if 'rotate' in transform_str:
            raise ValueError("Unsupported transform: rotate")

        matrices = []
        for match in re.finditer(r'(matrix|translate|scale)\s*\(([^)]+)\)', transform_str):
            cmd = match.group(1)
            args_str = match.group(2)
            args = [float(x) for x in re.split(r'[\s,]+', args_str.strip())]

            if cmd == 'matrix':
                if len(args) != 6:
                    raise ValueError("invalid matrix args")
                matrices.append(tuple(args))
            elif cmd == 'translate':
                tx = args[0]
                ty = args[1] if len(args) > 1 else 0
                matrices.append((1, 0, 0, 1, tx, ty))
            elif cmd == 'scale':
                sx = args[0]
                sy = args[1] if len(args) > 1 else sx
                matrices.append((sx, 0, 0, sy, 0, 0))

        if not matrices:
            return [(1, 0, 0, 1, 0, 0)]
        return matrices

    def _multiply_matrices(self, m1: Tuple[float, float, float, float, float, float],
                                 m2: Tuple[float, float, float, float, float, float]) -> Tuple[float, float, float, float, float, float]:
        a1, b1, c1, d1, e1, f1 = m1
        a2, b2, c2, d2, e2, f2 = m2
        return (
            a1*a2 + c1*b2,
            b1*a2 + d1*b2,
            a1*c2 + c1*d2,
            b1*c2 + d1*d2,
            a1*e2 + c1*f2 + e1,
            b1*e2 + d1*f2 + f1
        )

    def _apply_transform_to_path(self, d_str: str, matrix: Tuple[float, float, float, float, float, float]) -> str:
        if not d_str:
            return ""
        if matrix == (1, 0, 0, 1, 0, 0):
            # Just quantize
            matrix = None

        tokens = re.findall(r'[a-zA-Z]+|-?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?', d_str)
        if not tokens:
            return ""

        a, b, c, d_m, e, f = matrix if matrix else (1, 0, 0, 1, 0, 0)

        out_tokens = []
        i = 0
        cmd = ''

        while i < len(tokens):
            t = tokens[i]
            if re.match(r'^[a-zA-Z]$', t):
                if t.islower() and t != 'z':
                    raise ValueError(f"Relative path commands are not supported: {t}")
                cmd = t
                out_tokens.append(cmd)
                i += 1
                if cmd.upper() == 'Z':
                    continue

            # Read coordinates
            if cmd in ('M', 'L', 'T'):
                if i + 1 >= len(tokens):
                    raise ValueError("Not enough coords for M/L/T")
                x = float(tokens[i])
                y = float(tokens[i+1])
                if matrix:
                    nx = a*x + c*y + e
                    ny = b*x + d_m*y + f
                else:
                    nx, ny = x, y
                out_tokens.append(f"{round(nx, self.quantize_digits)}")
                out_tokens.append(f"{round(ny, self.quantize_digits)}")
                i += 2
            elif cmd in ('H', 'V'):
                raise ValueError("H/V commands not supported, must convert to L first or use M/L/C")
            elif cmd in ('S', 'Q'):
                if i + 3 >= len(tokens):
                    raise ValueError("Not enough coords for S/Q")
                x1, y1 = float(tokens[i]), float(tokens[i+1])
                x, y = float(tokens[i+2]), float(tokens[i+3])
                if matrix:
                    nx1 = a*x1 + c*y1 + e
                    ny1 = b*x1 + d_m*y1 + f
                    nx = a*x + c*y + e
                    ny = b*x + d_m*y + f
                else:
                    nx1, ny1, nx, ny = x1, y1, x, y
                out_tokens.extend([f"{round(nx1, self.quantize_digits)}", f"{round(ny1, self.quantize_digits)}", f"{round(nx, self.quantize_digits)}", f"{round(ny, self.quantize_digits)}"])
                i += 4
            elif cmd == 'C':
                if i + 5 >= len(tokens):
                    raise ValueError("Not enough coords for C")
                x1, y1 = float(tokens[i]), float(tokens[i+1])
                x2, y2 = float(tokens[i+2]), float(tokens[i+3])
                x, y = float(tokens[i+4]), float(tokens[i+5])
                if matrix:
                    nx1 = a*x1 + c*y1 + e
                    ny1 = b*x1 + d_m*y1 + f
                    nx2 = a*x2 + c*y2 + e
                    ny2 = b*x2 + d_m*y2 + f
                    nx = a*x + c*y + e
                    ny = b*x + d_m*y + f
                else:
                    nx1, ny1, nx2, ny2, nx, ny = x1, y1, x2, y2, x, y
                out_tokens.extend([f"{round(nx1, self.quantize_digits)}", f"{round(ny1, self.quantize_digits)}", f"{round(nx2, self.quantize_digits)}", f"{round(ny2, self.quantize_digits)}", f"{round(nx, self.quantize_digits)}", f"{round(ny, self.quantize_digits)}"])
                i += 6
            elif cmd == 'A':
                if i + 6 >= len(tokens):
                    raise ValueError("Not enough coords for A")
                rx, ry = float(tokens[i]), float(tokens[i+1])
                x_rot = float(tokens[i+2])
                large_arc = float(tokens[i+3])
                sweep = float(tokens[i+4])
                x, y = float(tokens[i+5]), float(tokens[i+6])

                if matrix and matrix != (1, 0, 0, 1, 0, 0):
                    # Applying matrix to arc is complex, reject if matrix has non-uniform scale or rotation/skew
                    if b != 0 or c != 0 or a != d_m:
                        raise ValueError("Non-uniform scale/rotation matrix applied to Arc (A) is not supported")
                    rx = rx * a
                    ry = ry * d_m
                    nx = a*x + e
                    ny = d_m*y + f
                else:
                    nx, ny = x, y

                out_tokens.extend([f"{round(abs(rx), self.quantize_digits)}", f"{round(abs(ry), self.quantize_digits)}", f"{round(x_rot, self.quantize_digits)}", f"{int(large_arc)}", f"{int(sweep)}", f"{round(nx, self.quantize_digits)}", f"{round(ny, self.quantize_digits)}"])
                i += 7
            else:
                # Should not reach here if commands are valid
                raise ValueError(f"Unknown path command: {cmd}")

        return " ".join(out_tokens)

    def _convert_line_to_path(self, elem: ET.Element) -> str:
        x1 = float(elem.get('x1', 0))
        y1 = float(elem.get('y1', 0))
        x2 = float(elem.get('x2', 0))
        y2 = float(elem.get('y2', 0))
        if x1 == x2 and y1 == y2:
            return ""
        return f"M {x1} {y1} L {x2} {y2}"

    def _convert_rect_to_path(self, elem: ET.Element) -> str:
        x = float(elem.get('x', 0))
        y = float(elem.get('y', 0))
        w = float(elem.get('width', 0))
        h = float(elem.get('height', 0))
        if w <= 0 or h <= 0:
            return ""
        # Does not support rx, ry for now, reject if present
        if elem.get('rx') or elem.get('ry'):
            raise ValueError("rect with rx/ry not supported")
        return f"M {x} {y} L {x+w} {y} L {x+w} {y+h} L {x} {y+h} Z"

    def _convert_circle_to_path(self, elem: ET.Element) -> str:
        cx = float(elem.get('cx', 0))
        cy = float(elem.get('cy', 0))
        r = float(elem.get('r', 0))
        if r <= 0:
            return ""
        # A circle as path using two arcs
        return f"M {cx-r} {cy} A {r} {r} 0 1 0 {cx+r} {cy} A {r} {r} 0 1 0 {cx-r} {cy} Z"

    def _convert_ellipse_to_path(self, elem: ET.Element) -> str:
        cx = float(elem.get('cx', 0))
        cy = float(elem.get('cy', 0))
        rx = float(elem.get('rx', 0))
        ry = float(elem.get('ry', 0))
        if rx <= 0 or ry <= 0:
            return ""
        return f"M {cx-rx} {cy} A {rx} {ry} 0 1 0 {cx+rx} {cy} A {rx} {ry} 0 1 0 {cx-rx} {cy} Z"

    def _convert_poly_to_path(self, elem: ET.Element, closed: bool) -> str:
        points_str = elem.get('points', '').strip()
        if not points_str:
            return ""
        # Parse points
        parts = re.split(r'[\s,]+', points_str)
        if len(parts) < 2 or len(parts) % 2 != 0:
            raise ValueError("invalid points in polygon/polyline")

        path = []
        for i in range(0, len(parts), 2):
            cmd = "M" if i == 0 else "L"
            path.append(f"{cmd} {parts[i]} {parts[i+1]}")

        if closed:
            path.append("Z")
        return " ".join(path)

    def _check_security_and_convert(self, root: ET.Element):
        for elem in root.iter():
            if elem.tag in self.rejected_elements:
                raise ValueError(f"Unsupported element: {elem.tag}")
            if elem.tag not in self.supported_elements:
                raise ValueError(f"Unsupported element: {elem.tag}")

            # Reject event handlers, network refs, external fonts, remote images
            for attr, val in elem.attrib.items():
                if attr.startswith('on'):
                    raise ValueError(f"Event handler not allowed: {attr}")
                if attr in self.rejected_attrs:
                    raise ValueError(f"Unsupported attribute: {attr}")
                if attr == 'href' or attr.endswith(':href'):
                    raise ValueError(f"External references not allowed: {attr}")

            # Convert primitives to path
            if elem.tag == 'rect':
                elem.attrib['d'] = self._convert_rect_to_path(elem)
                elem.tag = 'path'
            elif elem.tag == 'circle':
                elem.attrib['d'] = self._convert_circle_to_path(elem)
                elem.tag = 'path'
            elif elem.tag == 'ellipse':
                elem.attrib['d'] = self._convert_ellipse_to_path(elem)
                elem.tag = 'path'
            elif elem.tag == 'polygon':
                elem.attrib['d'] = self._convert_poly_to_path(elem, True)
                elem.tag = 'path'
            elif elem.tag == 'polyline':
                elem.attrib['d'] = self._convert_poly_to_path(elem, False)
                elem.tag = 'path'
            elif elem.tag == 'line':
                elem.attrib['d'] = self._convert_line_to_path(elem)
                elem.tag = 'path'

    def optimize(self, svg_string: str, concept_id: str, semantic_label: str,
                 license: str = None, source: str = None, source_hash: str = None) -> Dict[str, Any]:
        if self.unsafe_pattern.search(svg_string):
            raise ValueError("Unsafe XML detected: <!DOCTYPE or <!ENTITY declarations are not allowed.")

        try:
            root = ET.fromstring(svg_string)
        except ET.ParseError as e:
            raise ValueError(f"Failed to parse SVG: {e}")

        # Strip namespaces
        for elem in root.iter():
            if '}' in elem.tag:
                elem.tag = elem.tag.split('}', 1)[1]

        if root.tag != 'svg':
            raise ValueError("Root element must be <svg>")

        self._check_security_and_convert(root)

        viewBox_str = root.get('viewBox', '0 0 24 24')
        viewBox = [float(x) for x in re.split(r'[\s,]+', viewBox_str.strip())]

        unique_paths = []
        path_to_idx = {}
        unique_palette = []
        palette_to_idx = {}
        shapes = []

        def traverse(node: ET.Element, current_matrix: Tuple[float, float, float, float, float, float], current_fill: str):
            node_transform_str = node.get('transform', '')
            node_matrices = self._parse_transform(node_transform_str)
            m = current_matrix
            for nm in node_matrices:
                m = self._multiply_matrices(m, nm)

            fill = node.get('fill', current_fill)
            if not fill or fill == 'none':
                # Treat missing fill as black in SVG usually, but let's say #000000 if not specified
                # Actually, standard SVG default fill is black. Let's use #000000
                if fill != 'none':
                    fill = '#000000'

            if fill != 'none':
                # Convert fill colors to standard format (e.g., 6-hex)
                if re.match(r'^#[0-9a-fA-F]{3}$', fill):
                    # #abc -> #aabbcc
                    fill = '#' + fill[1]*2 + fill[2]*2 + fill[3]*2
                fill = fill.upper()
                # Ensure we only use valid hex colors
                if not re.match(r'^#[0-9A-F]{6}$', fill) and not re.match(r'^#[0-9A-F]{3}$', fill):
                    if fill.lower() == 'black': fill = '#000000'
                    elif fill.lower() == 'white': fill = '#FFFFFF'
                    else: raise ValueError(f"Unsupported color: {fill}")

            if node.tag == 'path':
                d = node.get('d', '')
                if d and fill != 'none':
                    transformed_d = self._apply_transform_to_path(d, m)
                    if transformed_d:
                        if transformed_d not in path_to_idx:
                            path_to_idx[transformed_d] = len(unique_paths)
                            unique_paths.append(transformed_d)
                        path_idx = path_to_idx[transformed_d]

                        if fill not in palette_to_idx:
                            palette_to_idx[fill] = len(unique_palette)
                            unique_palette.append(fill)
                        color_idx = palette_to_idx[fill]

                        shapes.append({
                            'path_idx': path_idx,
                            'color_idx': color_idx
                        })

            for child in node:
                if child.tag != 'defs': # Skip defs
                    traverse(child, m, fill)

        traverse(root, (1, 0, 0, 1, 0, 0), '#000000')

        token = {
            'concept_id': concept_id,
            'version': 1,
            'viewBox': viewBox,
            'paths': unique_paths,
            'palette': unique_palette,
            'semantic_label': semantic_label,
            'shapes': shapes
        }

        if license: token['license'] = license
        if source: token['source'] = source
        if source_hash: token['hash'] = source_hash

        # Verify it can be encoded and passes J053 size checks (visual_lexicon core)
        try:
            encode_token(token)
        except Exception as e:
            raise ValueError(f"Failed to encode token: {e}")

        # Verify geometry constraints and bounds
        verify_geometry_roundtrip(token)

        return token
