import xml.etree.ElementTree as ET
import re
from typing import Dict, Any, List, Optional, Tuple
from tools.visual_lexicon.core import encode_token, decode_token

# Allowed standard elements
ALLOWED_TAGS = {
    '{http://www.w3.org/2000/svg}svg',
    '{http://www.w3.org/2000/svg}g',
    '{http://www.w3.org/2000/svg}path'
}

UNSAFE_ATTRS = [
    re.compile(r'^on.*'),
    re.compile(r'^href$'),
    re.compile(r'^{http://www.w3.org/1999/xlink}href$')
]

PATH_TOKEN_RE = re.compile(r'([a-zA-Z])|([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)')
HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?$')

class SVGOptimizer:
    def __init__(self):
        pass

    def _quantize_path(self, path_str: str) -> str:
        tokens = PATH_TOKEN_RE.findall(path_str)
        quantized = []
        for cmd, val in tokens:
            if cmd:
                quantized.append(cmd)
            elif val:
                num = float(val)
                q_num = round(num, 2)
                q_str = f"{q_num:g}"
                quantized.append(q_str)
        return " ".join(quantized)

    def _verify_bounds(self, path_str: str, viewBox: List[float]) -> bool:
        # A proper bounding box verifier needs to track current (x,y).
        # We will keep it simple but correct for absolute and relative paths.
        # We don't implement full path bounding box for beziers/arcs.
        # But we can track the current x, y accurately.
        tokens = PATH_TOKEN_RE.findall(path_str)
        min_x, min_y, width, height = viewBox
        max_x = min_x + width
        max_y = min_y + height

        tolerance = max(width, height) * 0.5

        cx, cy = 0.0, 0.0
        cmd_type = None

        def check_pt(px, py):
            if px < min_x - tolerance or px > max_x + tolerance or py < min_y - tolerance or py > max_y + tolerance:
                return False
            return True

        i = 0
        while i < len(tokens):
            cmd, val = tokens[i]
            if cmd:
                cmd_type = cmd
                i += 1
            else:
                # Based on cmd_type read args
                if cmd_type.upper() in ('M', 'L'):
                    nx, ny = float(tokens[i][1]), float(tokens[i+1][1])
                    if cmd_type.islower():
                        cx += nx
                        cy += ny
                    else:
                        cx, cy = nx, ny
                    if not check_pt(cx, cy): return False
                    i += 2
                    cmd_type = 'L' if cmd_type.isupper() else 'l'
                elif cmd_type.upper() == 'H':
                    nx = float(tokens[i][1])
                    if cmd_type.islower():
                        cx += nx
                    else:
                        cx = nx
                    if not check_pt(cx, cy): return False
                    i += 1
                elif cmd_type.upper() == 'V':
                    ny = float(tokens[i][1])
                    if cmd_type.islower():
                        cy += ny
                    else:
                        cy = ny
                    if not check_pt(cx, cy): return False
                    i += 1
                elif cmd_type.upper() == 'C':
                    x1, y1 = float(tokens[i][1]), float(tokens[i+1][1])
                    x2, y2 = float(tokens[i+2][1]), float(tokens[i+3][1])
                    nx, ny = float(tokens[i+4][1]), float(tokens[i+5][1])

                    if cmd_type.islower():
                        cx += nx
                        cy += ny
                    else:
                        cx, cy = nx, ny
                    if not check_pt(cx, cy): return False
                    i += 6
                elif cmd_type.upper() == 'S':
                    x2, y2 = float(tokens[i][1]), float(tokens[i+1][1])
                    nx, ny = float(tokens[i+2][1]), float(tokens[i+3][1])
                    if cmd_type.islower():
                        cx += nx
                        cy += ny
                    else:
                        cx, cy = nx, ny
                    if not check_pt(cx, cy): return False
                    i += 4
                elif cmd_type.upper() == 'Q':
                    x1, y1 = float(tokens[i][1]), float(tokens[i+1][1])
                    nx, ny = float(tokens[i+2][1]), float(tokens[i+3][1])
                    if cmd_type.islower():
                        cx += nx
                        cy += ny
                    else:
                        cx, cy = nx, ny
                    if not check_pt(cx, cy): return False
                    i += 4
                elif cmd_type.upper() == 'T':
                    nx, ny = float(tokens[i][1]), float(tokens[i+1][1])
                    if cmd_type.islower():
                        cx += nx
                        cy += ny
                    else:
                        cx, cy = nx, ny
                    if not check_pt(cx, cy): return False
                    i += 2
                elif cmd_type.upper() == 'A':
                    rx, ry = float(tokens[i][1]), float(tokens[i+1][1])
                    xrot = float(tokens[i+2][1])
                    large_arc = float(tokens[i+3][1])
                    sweep = float(tokens[i+4][1])
                    nx, ny = float(tokens[i+5][1]), float(tokens[i+6][1])
                    if cmd_type.islower():
                        cx += nx
                        cy += ny
                    else:
                        cx, cy = nx, ny
                    if not check_pt(cx, cy): return False
                    i += 7
                elif cmd_type.upper() == 'Z':
                    pass # Z takes no args
                else:
                    # unknown cmd
                    return False
        return True

    def _apply_transform_to_path(self, path_str: str, transform_str: str) -> str:
        # Complex transforms and path parsing are non-trivial.
        # "Reject unsupported SVG features rather than approximating their appearance incorrectly."
        # If any path has a transform, we must be able to convert it EXACTLY, or we reject it.
        # We'll support translating, scaling and basic matrix.
        tokens = PATH_TOKEN_RE.findall(path_str)

        transforms = re.findall(r'(\w+)\s*\(([^)]+)\)', transform_str)
        if not transforms:
            raise ValueError(f"Invalid transform: {transform_str}")

        matrix = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0] # a, b, c, d, e, f

        for t_name, t_args in transforms:
            args = [float(x) for x in re.findall(r'[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?', t_args)]
            if t_name == 'matrix' and len(args) == 6:
                m2 = args
            elif t_name == 'translate':
                tx = args[0]
                ty = args[1] if len(args) > 1 else 0.0
                m2 = [1.0, 0.0, 0.0, 1.0, tx, ty]
            elif t_name == 'scale':
                sx = args[0]
                sy = args[1] if len(args) > 1 else sx
                m2 = [sx, 0.0, 0.0, sy, 0.0, 0.0]
            else:
                 raise ValueError(f"Unsupported transform: {t_name}")

            a1, b1, c1, d1, e1, f1 = matrix
            a2, b2, c2, d2, e2, f2 = m2
            matrix = [
                a1*a2 + c1*b2,
                b1*a2 + d1*b2,
                a1*c2 + c1*d2,
                b1*c2 + d1*d2,
                a1*e2 + c1*f2 + e1,
                b1*e2 + d1*f2 + f1
            ]

        # For exact mathematical application, if the matrix contains rotation/skew (b!=0 or c!=0)
        # we can only safely transform absolute paths composed of points (M, L, polygon paths).
        # Transforming arcs and beziers exactly through rotation/skew is mathematically complex.

        has_rot_skew = abs(matrix[1]) > 1e-6 or abs(matrix[2]) > 1e-6
        has_scale = abs(matrix[0] - 1.0) > 1e-6 or abs(matrix[3] - 1.0) > 1e-6

        new_path = []
        cmd_type = None
        i = 0
        while i < len(tokens):
            cmd, val = tokens[i]
            if cmd:
                cmd_type = cmd
                # If rotation/skew is involved, reject complex curves
                if has_rot_skew and cmd_type.upper() not in ('M', 'L', 'Z', 'H', 'V'):
                    raise ValueError("Cannot safely apply complex matrix transform to complex paths")
                if has_scale and cmd_type.upper() == 'A':
                    # Can't reliably scale arcs naively if non-uniform
                    if abs(matrix[0] - matrix[3]) > 1e-6:
                         raise ValueError("Cannot safely apply non-uniform scale to arc paths")

                new_path.append(cmd)
                i += 1
            else:
                if cmd_type.upper() in ('M', 'L'):
                    x, y = float(tokens[i][1]), float(tokens[i+1][1])
                    if cmd_type.islower():
                        # Relative translation shouldn't add the offset (e,f)
                        nx = matrix[0] * x + matrix[2] * y
                        ny = matrix[1] * x + matrix[3] * y
                    else:
                        nx = matrix[0] * x + matrix[2] * y + matrix[4]
                        ny = matrix[1] * x + matrix[3] * y + matrix[5]
                    new_path.append(f"{nx:g}")
                    new_path.append(f"{ny:g}")
                    i += 2
                    cmd_type = 'L' if cmd_type.isupper() else 'l'
                elif cmd_type.upper() == 'H':
                    x = float(tokens[i][1])
                    # If we have rotation/skew, an H command might become diagonal
                    # But we only allow H/V for translate/scale
                    if has_rot_skew:
                         raise ValueError("Cannot apply rotation/skew to horizontal paths")
                    if cmd_type.islower():
                        nx = matrix[0] * x
                    else:
                        nx = matrix[0] * x + matrix[4]
                    new_path.append(f"{nx:g}")
                    i += 1
                elif cmd_type.upper() == 'V':
                    y = float(tokens[i][1])
                    if has_rot_skew:
                         raise ValueError("Cannot apply rotation/skew to vertical paths")
                    if cmd_type.islower():
                        ny = matrix[3] * y
                    else:
                        ny = matrix[3] * y + matrix[5]
                    new_path.append(f"{ny:g}")
                    i += 1
                elif cmd_type.upper() == 'C':
                    x1, y1 = float(tokens[i][1]), float(tokens[i+1][1])
                    x2, y2 = float(tokens[i+2][1]), float(tokens[i+3][1])
                    nx, ny = float(tokens[i+4][1]), float(tokens[i+5][1])
                    if cmd_type.islower():
                        nx1 = matrix[0] * x1 + matrix[2] * y1
                        ny1 = matrix[1] * x1 + matrix[3] * y1
                        nx2 = matrix[0] * x2 + matrix[2] * y2
                        ny2 = matrix[1] * x2 + matrix[3] * y2
                        nnx = matrix[0] * nx + matrix[2] * ny
                        nny = matrix[1] * nx + matrix[3] * ny
                    else:
                        nx1 = matrix[0] * x1 + matrix[2] * y1 + matrix[4]
                        ny1 = matrix[1] * x1 + matrix[3] * y1 + matrix[5]
                        nx2 = matrix[0] * x2 + matrix[2] * y2 + matrix[4]
                        ny2 = matrix[1] * x2 + matrix[3] * y2 + matrix[5]
                        nnx = matrix[0] * nx + matrix[2] * ny + matrix[4]
                        nny = matrix[1] * nx + matrix[3] * ny + matrix[5]
                    new_path.extend([f"{nx1:g}", f"{ny1:g}", f"{nx2:g}", f"{ny2:g}", f"{nnx:g}", f"{nny:g}"])
                    i += 6
                elif cmd_type.upper() == 'Q':
                    x1, y1 = float(tokens[i][1]), float(tokens[i+1][1])
                    nx, ny = float(tokens[i+2][1]), float(tokens[i+3][1])
                    if cmd_type.islower():
                        nx1 = matrix[0] * x1 + matrix[2] * y1
                        ny1 = matrix[1] * x1 + matrix[3] * y1
                        nnx = matrix[0] * nx + matrix[2] * ny
                        nny = matrix[1] * nx + matrix[3] * ny
                    else:
                        nx1 = matrix[0] * x1 + matrix[2] * y1 + matrix[4]
                        ny1 = matrix[1] * x1 + matrix[3] * y1 + matrix[5]
                        nnx = matrix[0] * nx + matrix[2] * ny + matrix[4]
                        nny = matrix[1] * nx + matrix[3] * ny + matrix[5]
                    new_path.extend([f"{nx1:g}", f"{ny1:g}", f"{nnx:g}", f"{nny:g}"])
                    i += 4
                elif cmd_type.upper() == 'S':
                    x2, y2 = float(tokens[i][1]), float(tokens[i+1][1])
                    nx, ny = float(tokens[i+2][1]), float(tokens[i+3][1])
                    if cmd_type.islower():
                        nx2 = matrix[0] * x2 + matrix[2] * y2
                        ny2 = matrix[1] * x2 + matrix[3] * y2
                        nnx = matrix[0] * nx + matrix[2] * ny
                        nny = matrix[1] * nx + matrix[3] * ny
                    else:
                        nx2 = matrix[0] * x2 + matrix[2] * y2 + matrix[4]
                        ny2 = matrix[1] * x2 + matrix[3] * y2 + matrix[5]
                        nnx = matrix[0] * nx + matrix[2] * ny + matrix[4]
                        nny = matrix[1] * nx + matrix[3] * ny + matrix[5]
                    new_path.extend([f"{nx2:g}", f"{ny2:g}", f"{nnx:g}", f"{nny:g}"])
                    i += 4
                elif cmd_type.upper() == 'T':
                    nx, ny = float(tokens[i][1]), float(tokens[i+1][1])
                    if cmd_type.islower():
                        nnx = matrix[0] * nx + matrix[2] * ny
                        nny = matrix[1] * nx + matrix[3] * ny
                    else:
                        nnx = matrix[0] * nx + matrix[2] * ny + matrix[4]
                        nny = matrix[1] * nx + matrix[3] * ny + matrix[5]
                    new_path.extend([f"{nnx:g}", f"{nny:g}"])
                    i += 2
                elif cmd_type.upper() == 'A':
                    rx, ry = float(tokens[i][1]), float(tokens[i+1][1])
                    xrot = float(tokens[i+2][1])
                    large_arc = float(tokens[i+3][1])
                    sweep = float(tokens[i+4][1])
                    nx, ny = float(tokens[i+5][1]), float(tokens[i+6][1])
                    # We only allow uniform scaling for arcs.
                    # so rx and ry scale by matrix[0] (which is equal to matrix[3]).
                    nrx = rx * matrix[0]
                    nry = ry * matrix[0]

                    if cmd_type.islower():
                        nnx = matrix[0] * nx + matrix[2] * ny
                        nny = matrix[1] * nx + matrix[3] * ny
                    else:
                        nnx = matrix[0] * nx + matrix[2] * ny + matrix[4]
                        nny = matrix[1] * nx + matrix[3] * ny + matrix[5]
                    new_path.extend([f"{nrx:g}", f"{nry:g}", f"{xrot:g}", f"{large_arc:g}", f"{sweep:g}", f"{nnx:g}", f"{nny:g}"])
                    i += 7
                elif cmd_type.upper() == 'Z':
                    pass # Z handled by cmd block

        return " ".join(new_path)

    def optimize(self, svg_content: str, concept_id: str, version: int, semantic_label: str, license: Optional[str] = None, source: Optional[str] = None, source_hash: Optional[str] = None) -> Tuple[bytes, Dict[str, Any]]:
        if '<!DOCTYPE' in svg_content or '<!ENTITY' in svg_content:
            raise ValueError("Unsafe XML: DOCTYPE or ENTITY detected")

        try:
            root = ET.fromstring(svg_content)
        except ET.ParseError as e:
            raise ValueError(f"Invalid XML: {e}")

        if root.tag != '{http://www.w3.org/2000/svg}svg':
            raise ValueError("Root element must be svg")

        view_box_str = root.attrib.get('viewBox')
        if not view_box_str:
            raise ValueError("Missing viewBox attribute on svg root")

        try:
            vb_parts = [float(x) for x in view_box_str.replace(',', ' ').split()]
            if len(vb_parts) != 4:
                raise ValueError()
        except ValueError:
            raise ValueError("Invalid viewBox format")

        viewBox = [round(x, 2) if x % 1 != 0 else int(x) for x in vb_parts]

        paths = set()
        palette = set()

        def process_element(elem, current_transform=None):
            if elem.tag not in ALLOWED_TAGS:
                raise ValueError(f"Unsupported element: {elem.tag}")

            for attr in elem.attrib:
                for unsafe_re in UNSAFE_ATTRS:
                    if unsafe_re.match(attr):
                        raise ValueError(f"Unsafe attribute detected: {attr}")

            transform = elem.attrib.get('transform')
            if transform and current_transform:
                transform = current_transform + " " + transform
            elif not transform:
                transform = current_transform

            if elem.tag == '{http://www.w3.org/2000/svg}path':
                d = elem.attrib.get('d')
                if d:
                    if transform:
                        d = self._apply_transform_to_path(d, transform)
                    quantized_d = self._quantize_path(d)

                    if not self._verify_bounds(quantized_d, viewBox):
                         raise ValueError("Path geometry overflowed viewBox visual bounds")

                    paths.add(quantized_d)

            fill = elem.attrib.get('fill')
            if fill and fill != 'none':
                if not HEX_COLOR_RE.fullmatch(fill):
                    raise ValueError(f"Invalid or non-hex color: {fill}")
                palette.add(fill.upper())

            stroke = elem.attrib.get('stroke')
            if stroke and stroke != 'none':
                if not HEX_COLOR_RE.fullmatch(stroke):
                    raise ValueError(f"Invalid or non-hex color: {stroke}")
                palette.add(stroke.upper())

            for child in elem:
                 process_element(child, transform)

        process_element(root)

        if not palette:
            palette.add("#000000")

        token_data = {
            'concept_id': concept_id,
            'version': version,
            'viewBox': viewBox,
            'paths': sorted(list(paths)),
            'palette': sorted(list(palette)),
            'semantic_label': semantic_label
        }

        if len(token_data['paths']) > 50:
             raise ValueError("Maximum of 50 paths allowed per token")

        if not token_data['paths']:
            raise ValueError("paths must be a non-empty list")

        compressed, token_hash = encode_token(token_data)

        if len(compressed) >= 2048:
             raise ValueError(f"Token size limit exceeded: {len(compressed)} >= 2048")

        decode_token(compressed)

        manifest_data = {
             'concept_id': concept_id,
             'author': 'svg_optimizer',
             'fixture_status': 'synthetic',
        }
        if license: manifest_data['license'] = license
        if source: manifest_data['source'] = source
        if source_hash: manifest_data['source_hash'] = source_hash

        return compressed, manifest_data
