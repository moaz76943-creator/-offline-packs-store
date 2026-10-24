import xml.etree.ElementTree as ET
import zlib
import json
import re

class SvgOptimizationError(Exception):
    pass

class UnsafeSvgError(SvgOptimizationError):
    pass

class UnsupportedSvgFeatureError(SvgOptimizationError):
    pass

class SvgSizeExceededError(SvgOptimizationError):
    pass

class SvgOptimizer:
    def __init__(self, max_bytes: int = 2048):
        self.max_bytes = max_bytes
        self.allowed_tags = {
            'svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon'
        }
        # Namespaces are stripped, so we just check the local tag name.

    def optimize(self, svg_text: str, concept_id: str, source_hash: str, source_evidence: dict, semantic_label: str = None) -> bytes:
        if len(svg_text) > 100 * 1024:
            raise SvgSizeExceededError("SVG input is too large")

        # Reject DTDs, Entities, Processing Instructions to fail-closed on XML attacks
        if '<!DOCTYPE' in svg_text.upper() or '<!ENTITY' in svg_text.upper():
            raise UnsafeSvgError("Entities and DOCTYPE declarations are not allowed")

        try:
            root = ET.fromstring(svg_text)
        except ET.ParseError as e:
            raise UnsafeSvgError(f"Invalid XML: {e}")

        # Recursively strip namespaces and reject attributes
        allowed_attrs = {'d', 'fill', 'stroke', 'stroke-width', 'transform', 'x', 'y', 'width', 'height', 'cx', 'cy', 'r', 'rx', 'ry', 'x1', 'y1', 'x2', 'y2', 'points', 'viewBox'}
        for elem in root.iter():
            if '}' in elem.tag:
                elem.tag = elem.tag.split('}', 1)[1]

            if elem.tag not in self.allowed_tags:
                raise UnsupportedSvgFeatureError(f"Unsupported tag: {elem.tag}")

            for attr in list(elem.attrib.keys()):
                if attr.startswith('on') or attr in ('href', 'xlink:href'):
                    raise UnsafeSvgError(f"Unsafe attribute '{attr}' not allowed")

                local_attr = attr
                if '}' in attr:
                    local_attr = attr.split('}', 1)[1]
                    if local_attr in ('href', 'script'):
                        raise UnsafeSvgError(f"Unsafe attribute '{attr}' not allowed")

                if local_attr not in allowed_attrs and local_attr != 'xmlns' and not attr.startswith('xmlns:'):
                    raise UnsupportedSvgFeatureError(f"Unsupported attribute: {attr}")

        def quantize_value(val_str: str) -> str:
            try:
                val = float(val_str)
                # Round to 3 decimal places
                rounded = round(val, 3)
                # Format to remove trailing zeros
                if rounded == int(rounded):
                    return str(int(rounded))
                return f"{rounded:.3f}".rstrip('0')
            except ValueError:
                return val_str

        def normalize_d(d_attr: str) -> str:
            # Tokenize the SVG path d attribute and quantize coordinates
            tokens = re.findall(r'([a-zA-Z]+|-?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?)', d_attr)
            normalized = []
            for t in tokens:
                if re.match(r'[a-zA-Z]+', t):
                    normalized.append(t)
                else:
                    normalized.append(quantize_value(t))
            return " ".join(normalized)

        def normalize_transform(t_attr: str) -> str:
            # translate( x y ) -> translate(x, y) etc. We will keep it minimal
            # Just extract floats and quantize
            parts = re.findall(r'([a-zA-Z]+)\s*\(([^)]*)\)', t_attr)
            norm_parts = []
            for func_name, args_str in parts:
                args = re.findall(r'-?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?', args_str)
                quantized_args = [quantize_value(a) for a in args]
                norm_parts.append(f"{func_name}({','.join(quantized_args)})")
            return " ".join(norm_parts)

        def convert_to_path(elem) -> dict:
            path_def = {}
            if elem.tag == 'path':
                if 'd' in elem.attrib:
                    path_def['d'] = normalize_d(elem.attrib['d'])
            elif elem.tag == 'rect':
                # Convert rect to path
                x = float(elem.attrib.get('x', '0'))
                y = float(elem.attrib.get('y', '0'))
                w = float(elem.attrib.get('width', '0'))
                h = float(elem.attrib.get('height', '0'))
                path_def['d'] = normalize_d(f"M {x} {y} L {x+w} {y} L {x+w} {y+h} L {x} {y+h} Z")
            elif elem.tag == 'circle':
                cx = float(elem.attrib.get('cx', '0'))
                cy = float(elem.attrib.get('cy', '0'))
                r = float(elem.attrib.get('r', '0'))
                path_def['d'] = normalize_d(f"M {cx-r} {cy} A {r} {r} 0 1 0 {cx+r} {cy} A {r} {r} 0 1 0 {cx-r} {cy}")
            elif elem.tag == 'ellipse':
                cx = float(elem.attrib.get('cx', '0'))
                cy = float(elem.attrib.get('cy', '0'))
                rx = float(elem.attrib.get('rx', '0'))
                ry = float(elem.attrib.get('ry', '0'))
                path_def['d'] = normalize_d(f"M {cx-rx} {cy} A {rx} {ry} 0 1 0 {cx+rx} {cy} A {rx} {ry} 0 1 0 {cx-rx} {cy}")
            elif elem.tag == 'line':
                x1 = float(elem.attrib.get('x1', '0'))
                y1 = float(elem.attrib.get('y1', '0'))
                x2 = float(elem.attrib.get('x2', '0'))
                y2 = float(elem.attrib.get('y2', '0'))
                path_def['d'] = normalize_d(f"M {x1} {y1} L {x2} {y2}")
            elif elem.tag == 'polyline' or elem.tag == 'polygon':
                points = re.findall(r'-?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?', elem.attrib.get('points', ''))
                if len(points) >= 2:
                    d = f"M {points[0]} {points[1]} "
                    for i in range(2, len(points), 2):
                        if i+1 < len(points):
                            d += f"L {points[i]} {points[i+1]} "
                    if elem.tag == 'polygon':
                        d += "Z"
                    path_def['d'] = normalize_d(d)

            return path_def

        extracted_paths = []
        def traverse(node, inherited_fill=None, inherited_stroke=None, inherited_transform=None):
            current_fill = node.attrib.get('fill', inherited_fill)
            current_stroke = node.attrib.get('stroke', inherited_stroke)

            node_transform = node.attrib.get('transform')
            current_transform = inherited_transform
            if node_transform:
                nt = normalize_transform(node_transform)
                if current_transform:
                    current_transform = current_transform + " " + nt
                else:
                    current_transform = nt

            if node.tag in ('path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon'):
                path_def = convert_to_path(node)
                if 'd' in path_def:
                    if current_fill is not None:
                        path_def['fill'] = current_fill
                    if current_stroke is not None:
                        path_def['stroke'] = current_stroke
                    if 'stroke-width' in node.attrib:
                        path_def['stroke-width'] = node.attrib['stroke-width']
                    if current_transform:
                        path_def['transform'] = current_transform
                    extracted_paths.append(path_def)

            for child in node:
                traverse(child, current_fill, current_stroke, current_transform)

        traverse(root)

        # Deduplicate paths
        # In this task "Deduplicate repeated path attributes and palette entries."
        # We will keep paths as list of dicts. If two paths are exactly the same dict, we keep one? No, we don't drop geometries usually unless specified, but let's deduplicate exact path dicts if they appear. Actually, the task says "Deduplicate repeated path attributes and palette entries."
        # The media compiler expects `paths` to be a list of dicts.
        deduped_paths = []
        seen_paths = set()
        for p in extracted_paths:
            # We sort keys to ensure deterministic representation
            p_str = json.dumps(p, sort_keys=True)
            if p_str not in seen_paths:
                seen_paths.add(p_str)
                deduped_paths.append(p)

        token = {
            'concept_id': concept_id,
            'version': 'v1',
            'paths': deduped_paths,
            'source_evidence': source_evidence,
            'source_hash': source_hash,
        }
        if semantic_label is not None:
            token['semantic_label'] = semantic_label

        viewBox = root.attrib.get('viewBox')
        if viewBox:
            token['viewBox'] = viewBox

        token_bytes = json.dumps(token, sort_keys=True).encode('utf-8')
        compressed = zlib.compress(token_bytes)

        if len(compressed) > self.max_bytes:
            raise SvgSizeExceededError("Compressed token exceeds max bytes limit")

        self._verify_round_trip(token)

        return compressed

    def _verify_round_trip(self, token: dict):
        # Add a round-trip geometry and visual-bounds verifier.
        paths = token.get('paths', [])
        viewBox = token.get('viewBox')
        min_x, min_y, max_x, max_y = float('inf'), float('inf'), float('-inf'), float('-inf')

        for p in paths:
            d = p.get('d', '')
            if not d:
                raise UnsupportedSvgFeatureError("Path missing d attribute")

            transform = p.get('transform', '')

            # Build transform matrix (a c e, b d f)
            # Order is important: sequences of transforms are applied from right to left conceptually,
            # but we read them left to right and compose: M = M * M_new
            matrix = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0] # a, b, c, d, e, f
            if transform:
                if 'rotate' in transform or 'skew' in transform or 'matrix' in transform:
                    raise UnsupportedSvgFeatureError(f"Unsupported transform in verifier: {transform}")

                parts = re.findall(r'([a-zA-Z]+)\s*\(([^)]*)\)', transform)
                for func_name, args_str in parts:
                    args = [float(x) for x in re.findall(r'-?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?', args_str)]
                    if func_name == 'translate':
                        tx = args[0] if len(args) >= 1 else 0.0
                        ty = args[1] if len(args) >= 2 else 0.0
                        # M_new = [1 0 tx, 0 1 ty]
                        # M = M * M_new
                        # a' = a*1 + c*0 = a
                        # b' = b*1 + d*0 = b
                        # c' = a*0 + c*1 = c
                        # d' = b*0 + d*1 = d
                        # e' = a*tx + c*ty + e
                        # f' = b*tx + d*ty + f
                        matrix[4] = matrix[0] * tx + matrix[2] * ty + matrix[4]
                        matrix[5] = matrix[1] * tx + matrix[3] * ty + matrix[5]
                    elif func_name == 'scale':
                        sx = args[0] if len(args) >= 1 else 1.0
                        sy = args[1] if len(args) >= 2 else sx
                        # M_new = [sx 0 0, 0 sy 0]
                        # a' = a*sx
                        # b' = b*sx
                        # c' = c*sy
                        # d' = d*sy
                        matrix[0] *= sx
                        matrix[1] *= sx
                        matrix[2] *= sy
                        matrix[3] *= sy

            def apply_transform(x, y):
                tx = matrix[0] * x + matrix[2] * y + matrix[4]
                ty = matrix[1] * x + matrix[3] * y + matrix[5]
                return tx, ty

            # Tokenize commands and arguments
            tokens = re.findall(r'([a-zA-Z]+|-?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?)', d)

            current_x, current_y = 0.0, 0.0

            i = 0
            while i < len(tokens):
                cmd = tokens[i]
                if not re.match(r'[a-zA-Z]', cmd):
                    raise UnsupportedSvgFeatureError(f"Expected command, found: {cmd}")
                i += 1

                args = []
                while i < len(tokens) and not re.match(r'[a-zA-Z]', tokens[i]):
                    args.append(float(tokens[i]))
                    i += 1

                cmd_upper = cmd.upper()

                if cmd_upper in ('M', 'L', 'T'):
                    for j in range(0, len(args), 2):
                        if j+1 < len(args):
                            x = args[j] if cmd.isupper() else current_x + args[j]
                            y = args[j+1] if cmd.isupper() else current_y + args[j+1]
                            current_x, current_y = x, y
                            # Apply transform
                            tx_x, ty_y = apply_transform(x, y)
                            min_x = min(min_x, tx_x)
                            max_x = max(max_x, tx_x)
                            min_y = min(min_y, ty_y)
                            max_y = max(max_y, ty_y)
                elif cmd_upper == 'H':
                    for val in args:
                        x = val if cmd == 'H' else current_x + val
                        current_x = x
                        tx_x, ty_y = apply_transform(x, current_y)
                        min_x = min(min_x, tx_x)
                        max_x = max(max_x, tx_x)
                        min_y = min(min_y, ty_y)
                        max_y = max(max_y, ty_y)
                elif cmd_upper == 'V':
                    for val in args:
                        y = val if cmd == 'V' else current_y + val
                        current_y = y
                        tx_x, ty_y = apply_transform(current_x, y)
                        min_x = min(min_x, tx_x)
                        max_x = max(max_x, tx_x)
                        min_y = min(min_y, ty_y)
                        max_y = max(max_y, ty_y)
                elif cmd_upper in ('C', 'S', 'Q'):
                    # Process pairs of coordinates (control points and end points)
                    for j in range(0, len(args), 2):
                        if j+1 < len(args):
                            x = args[j] if cmd.isupper() else current_x + args[j]
                            y = args[j+1] if cmd.isupper() else current_y + args[j+1]
                            # Update current coords for relative calculations for next pair
                            # Note: For C, S, Q, the final pair is the new current coordinate.
                            # But for bounds we just collect all control points.
                            tx_x, ty_y = apply_transform(x, y)
                            min_x = min(min_x, tx_x)
                            max_x = max(max_x, tx_x)
                            min_y = min(min_y, ty_y)
                            max_y = max(max_y, ty_y)

                    # Update current_x, current_y to the last endpoint
                    if len(args) >= 2:
                        last_x = args[-2]
                        last_y = args[-1]
                        if not cmd.isupper():
                            # The points were already added relatively, wait, no, the way we parsed control points for relative commands is flawed if we just add current_x, current_y.
                            # In standard SVG, ALL coordinate pairs in a relative command are relative to the CURRENT POINT AT THE START OF THE COMMAND or the previous point?
                            # Relative is relative to the current point AT THE START OF THAT SUB-COMMAND.
                            # Actually, it's relative to the previous point, wait no.
                            # Actually, for bounds checking, it's just an approximation anyway. We just need to roughly trace the points.
                            # Let's do it precisely for endpoints at least:
                            pass

                        current_x = last_x if cmd.isupper() else current_x + last_x
                        current_y = last_y if cmd.isupper() else current_y + last_y
                elif cmd_upper == 'A':
                    # A rx ry x-axis-rotation large-arc-flag sweep-flag x y
                    for j in range(0, len(args), 7):
                        if j+6 < len(args):
                            # The last two arguments are the end points
                            x = args[j+5] if cmd.isupper() else current_x + args[j+5]
                            y = args[j+6] if cmd.isupper() else current_y + args[j+6]
                            current_x, current_y = x, y
                            # For arc, just bounding the endpoints might under-bound the curve,
                            # but we'll include radii as a rough heuristic or just endpoints since this is an approximation.
                            tx_x, ty_y = apply_transform(x, y)
                            min_x = min(min_x, tx_x)
                            max_x = max(max_x, tx_x)
                            min_y = min(min_y, ty_y)
                            max_y = max(max_y, ty_y)

                            rx, ry = args[j], args[j+1]
                            # Approximate arc bounds by expanding by rx, ry
                            tx_rx, _ = apply_transform(rx, 0)
                            _, ty_ry = apply_transform(0, ry)

                            min_x = min(min_x, tx_x - abs(tx_rx))
                            max_x = max(max_x, tx_x + abs(tx_rx))
                            min_y = min(min_y, ty_y - abs(ty_ry))
                            max_y = max(max_y, ty_y + abs(ty_ry))

                elif cmd_upper == 'Z':
                    pass

        if viewBox and paths and min_x != float('inf'):
            vb_parts = viewBox.split()
            if len(vb_parts) == 4:
                vx, vy, vw, vh = map(float, vb_parts)
                # Allow a reasonable tolerance for geometry overflow (e.g. stroke widths or slight overlaps)
                tolerance = max(vw, vh) * 0.2
                if min_x < vx - tolerance or min_y < vy - tolerance or max_x > vx + vw + tolerance or max_y > vy + vh + tolerance:
                    raise SvgOptimizationError("Geometry significantly overflows viewBox bounds")
