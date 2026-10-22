import xml.etree.ElementTree as ET
import re

class SvgOptimizer:
    def __init__(self):
        pass

    UNSAFE_TAGS = {
        'script', 'foreignObject', 'image', 'iframe', 'object', 'embed', 'style'
    }
    UNSUPPORTED_FEATURES = {
        'filter', 'mask', 'clipPath', 'linearGradient', 'radialGradient', 'pattern'
    }

    def _strip_ns(self, tag: str) -> str:
        """Strips XML namespace from a tag."""
        if '}' in tag:
            return tag.split('}', 1)[1]
        return tag

    def reject_unsafe_and_unsupported(self, element: ET.Element):
        """Recursively checks for unsafe tags/attributes and unsupported features."""
        tag = self._strip_ns(element.tag)

        if tag in self.UNSAFE_TAGS:
            raise ValueError(f"Unsafe tag rejected: {tag}")
        if tag in self.UNSUPPORTED_FEATURES:
            raise ValueError(f"Unsupported feature rejected: {tag}")

        for attr, value in element.attrib.items():
            attr_lower = attr.lower()
            if attr_lower.startswith('on'):
                raise ValueError(f"Event handler attribute rejected: {attr}")
            if attr_lower in ('href', '{http://www.w3.org/1999/xlink}href'):
                if value.startswith('http://') or value.startswith('https://') or value.startswith('//'):
                    raise ValueError(f"Network reference rejected in attribute {attr}: {value}")

            if attr_lower == 'style':
                if 'url(' in value.lower():
                    raise ValueError(f"External reference rejected in style attribute: {value}")

        for child in element:
            self.reject_unsafe_and_unsupported(child)

    def parse_transform(self, transform_str: str):
        """Parses an SVG transform string into a 3x3 matrix."""
        matrix = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        if not transform_str:
            return matrix

        # Extract transform commands like matrix(a,b,c,d,e,f) or translate(x,y)
        commands = re.findall(r'(\w+)\s*\(([^)]+)\)', transform_str)
        for cmd, args_str in commands:
            if cmd in ('rotate', 'skewX', 'skewY'):
                raise ValueError(f"Unsupported transform command: {cmd}")

            args = [float(x) for x in re.split(r'[,\s]+', args_str.strip()) if x]
            m = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
            if cmd == 'matrix' and len(args) == 6:
                m = [[args[0], args[2], args[4]],
                     [args[1], args[3], args[5]],
                     [0,       0,       1]]
            elif cmd == 'translate':
                tx = args[0]
                ty = args[1] if len(args) > 1 else 0.0
                m = [[1, 0, tx],
                     [0, 1, ty],
                     [0, 0, 1]]
            elif cmd == 'scale':
                sx = args[0]
                sy = args[1] if len(args) > 1 else sx
                m = [[sx, 0, 0],
                     [0, sy, 0],
                     [0, 0, 1]]
            else:
                raise ValueError(f"Unsupported transform command: {cmd}")

            # For simplicity, we implement only basic matrix multiplication
            # Multiply matrix * m
            new_matrix = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
            for i in range(3):
                for j in range(3):
                    for k in range(3):
                        new_matrix[i][j] += matrix[i][k] * m[k][j]
            matrix = new_matrix

        return matrix

    def apply_matrix_to_point(self, matrix, x, y):
        """Applies a 3x3 affine transformation matrix to a 2D point (x, y)."""
        nx = matrix[0][0] * x + matrix[0][1] * y + matrix[0][2]
        ny = matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]
        return nx, ny

    def shape_to_path(self, element: ET.Element) -> str:
        """Converts basic SVG shapes to a 'd' path string."""
        tag = self._strip_ns(element.tag)
        d = ""

        if tag == 'path':
            d = element.get('d', '')
        elif tag == 'rect':
            x = float(element.get('x', 0))
            y = float(element.get('y', 0))
            w = float(element.get('width', 0))
            h = float(element.get('height', 0))
            d = f"M {x} {y} H {x+w} V {y+h} H {x} Z"
        elif tag == 'circle':
            cx = float(element.get('cx', 0))
            cy = float(element.get('cy', 0))
            r = float(element.get('r', 0))
            # Approximate circle with 4 arcs or just standard SVG arcs
            # SVG arc: A rx ry x-axis-rotation large-arc-flag sweep-flag x y
            d = f"M {cx-r} {cy} A {r} {r} 0 1 0 {cx+r} {cy} A {r} {r} 0 1 0 {cx-r} {cy} Z"
        elif tag == 'ellipse':
            cx = float(element.get('cx', 0))
            cy = float(element.get('cy', 0))
            rx = float(element.get('rx', 0))
            ry = float(element.get('ry', 0))
            d = f"M {cx-rx} {cy} A {rx} {ry} 0 1 0 {cx+rx} {cy} A {rx} {ry} 0 1 0 {cx-rx} {cy} Z"
        elif tag == 'line':
            x1 = float(element.get('x1', 0))
            y1 = float(element.get('y1', 0))
            x2 = float(element.get('x2', 0))
            y2 = float(element.get('y2', 0))
            d = f"M {x1} {y1} L {x2} {y2}"
        elif tag in ('polygon', 'polyline'):
            points_str = element.get('points', '')
            points = [float(p) for p in re.split(r'[,\s]+', points_str.strip()) if p]
            if len(points) >= 2:
                d = f"M {points[0]} {points[1]}"
                for i in range(2, len(points), 2):
                    d += f" L {points[i]} {points[i+1]}"
                if tag == 'polygon':
                    d += " Z"

        return d

    def parse_path_commands(self, d: str):
        """A simple generator that tokenizes path commands and their arguments."""
        # Split into commands and numbers
        # e.g. M 10 20 L 30 40 -> ['M', '10', '20', 'L', '30', '40']
        tokens = re.findall(r'[a-zA-Z]+|-?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?', d)

        i = 0
        while i < len(tokens):
            cmd = tokens[i]
            if cmd.isalpha():
                i += 1
                args = []
                while i < len(tokens) and not tokens[i].isalpha():
                    args.append(float(tokens[i]))
                    i += 1
                yield cmd, args
            else:
                # Implicit command based on last command if needed, though robust SVG should have explicit commands or we handle it if requested.
                # For simplicity in this implementation, we assume explicit commands or at least correctly formatted paths.
                raise ValueError(f"Unexpected token in path: {cmd}")

    def transform_path(self, d: str, matrix) -> str:
        """Parses a path, applies transformation matrix, and returns normalized absolute path."""
        if not d:
            return ""

        new_d = []
        current_x, current_y = 0.0, 0.0
        start_x, start_y = 0.0, 0.0

        for cmd, args in self.parse_path_commands(d):
            is_relative = cmd.islower()
            cmd_upper = cmd.upper()

            if cmd_upper == 'M':
                for i in range(0, len(args), 2):
                    x, y = args[i], args[i+1]
                    if is_relative and (i > 0 or current_x != 0 or current_y != 0):
                        x += current_x
                        y += current_y
                    current_x, current_y = x, y
                    if i == 0:
                        start_x, start_y = x, y

                    tx, ty = self.apply_matrix_to_point(matrix, x, y)
                    new_d.append(f"{'M' if i == 0 else 'L'} {tx:.2f} {ty:.2f}")

            elif cmd_upper == 'L':
                for i in range(0, len(args), 2):
                    x, y = args[i], args[i+1]
                    if is_relative:
                        x += current_x
                        y += current_y
                    current_x, current_y = x, y

                    tx, ty = self.apply_matrix_to_point(matrix, x, y)
                    new_d.append(f"L {tx:.2f} {ty:.2f}")

            elif cmd_upper == 'H':
                for x in args:
                    if is_relative:
                        x += current_x
                    current_x = x
                    tx, ty = self.apply_matrix_to_point(matrix, current_x, current_y)
                    new_d.append(f"L {tx:.2f} {ty:.2f}")

            elif cmd_upper == 'V':
                for y in args:
                    if is_relative:
                        y += current_y
                    current_y = y
                    tx, ty = self.apply_matrix_to_point(matrix, current_x, current_y)
                    new_d.append(f"L {tx:.2f} {ty:.2f}")

            elif cmd_upper == 'Z':
                current_x, current_y = start_x, start_y
                new_d.append("Z")

            elif cmd_upper in ('C', 'S', 'Q', 'T'):
                points_per_segment = 6 if cmd_upper == 'C' else (2 if cmd_upper == 'T' else 4)
                transformed_args = []
                for i in range(0, len(args), points_per_segment):
                    segment_args = args[i:i+points_per_segment]
                    if len(segment_args) < points_per_segment:
                        break # Truncated segment, ignore

                    for j in range(0, len(segment_args), 2):
                        x, y = segment_args[j], segment_args[j+1]
                        if is_relative:
                            x += current_x
                            y += current_y
                        tx, ty = self.apply_matrix_to_point(matrix, x, y)
                        transformed_args.append(f"{tx:.2f} {ty:.2f}")

                    # Update current position to the end of this segment
                    last_x, last_y = segment_args[-2], segment_args[-1]
                    if is_relative:
                        current_x += last_x
                        current_y += last_y
                    else:
                        current_x, current_y = last_x, last_y

                new_d.append(f"{cmd_upper} {' '.join(transformed_args)}")

            elif cmd_upper == 'A':
                # Arcs: A rx ry x-axis-rotation large-arc-flag sweep-flag x y
                for i in range(0, len(args), 7):
                    rx, ry = args[i], args[i+1]
                    rot = args[i+2]
                    laf, sf = args[i+3], args[i+4]
                    x, y = args[i+5], args[i+6]

                    if is_relative:
                        x += current_x
                        y += current_y

                    # Transforming radii and rotation for arcs is complex.
                    # For affine transformations, we simplify or assume uniform scale.
                    # This is a best-effort approximation for generic matrices.
                    # Specifically, scale affects rx, ry.
                    sx = (matrix[0][0]**2 + matrix[1][0]**2)**0.5
                    sy = (matrix[0][1]**2 + matrix[1][1]**2)**0.5
                    trx = rx * sx
                    try_ = ry * sy

                    tx, ty = self.apply_matrix_to_point(matrix, x, y)
                    new_d.append(f"A {trx:.2f} {try_:.2f} {rot} {laf} {sf} {tx:.2f} {ty:.2f}")

                    current_x, current_y = x, y
            else:
                 raise ValueError(f"Unsupported path command: {cmd}")

        return " ".join(new_d).strip()

    def verify_geometry(self, paths: list, viewBox: list):
        """Samples paths to verify they don't significantly exceed the viewBox."""
        if not viewBox or len(viewBox) != 4:
            return

        vx, vy, vw, vh = viewBox
        min_x, min_y = vx, vy
        max_x, max_y = vx + vw, vy + vh

        tolerance = max(vw, vh) * 0.1  # 10% tolerance

        for d in paths:
            for cmd, args in self.parse_path_commands(d):
                if cmd.upper() in ('M', 'L', 'T'):
                    for i in range(0, len(args), 2):
                        x, y = args[i], args[i+1]
                        if x < min_x - tolerance or x > max_x + tolerance or \
                           y < min_y - tolerance or y > max_y + tolerance:
                            raise ValueError(f"Geometry overflow: point ({x}, {y}) exceeds viewBox {viewBox} with tolerance {tolerance}")
                elif cmd.upper() in ('Q', 'S'):
                    for i in range(0, len(args), 4):
                        x, y = args[i+2], args[i+3]
                        if x < min_x - tolerance or x > max_x + tolerance or \
                           y < min_y - tolerance or y > max_y + tolerance:
                            raise ValueError(f"Geometry overflow: point ({x}, {y}) exceeds viewBox {viewBox} with tolerance {tolerance}")
                elif cmd.upper() == 'C':
                    for i in range(0, len(args), 6):
                        x, y = args[i+4], args[i+5]
                        if x < min_x - tolerance or x > max_x + tolerance or \
                           y < min_y - tolerance or y > max_y + tolerance:
                            raise ValueError(f"Geometry overflow: point ({x}, {y}) exceeds viewBox {viewBox} with tolerance {tolerance}")
                elif cmd.upper() == 'A':
                    for i in range(0, len(args), 7):
                        x, y = args[i+5], args[i+6]
                        if x < min_x - tolerance or x > max_x + tolerance or \
                           y < min_y - tolerance or y > max_y + tolerance:
                            raise ValueError(f"Geometry overflow: point ({x}, {y}) exceeds viewBox {viewBox} with tolerance {tolerance}")

    def optimize(self, svg_content: str, concept_id: str, semantic_label: str, license_evidence: dict, source_hash: str) -> bytes:
        """
        Main optimization pipeline:
        1. Parse securely
        2. Reject unsafe/unsupported
        3. Traverse, extract shapes, convert to paths, apply matrices
        4. Quantize and deduplicate
        5. Verify bounds
        6. Encode to J053 token
        """
        root = self.parse_securely(svg_content)
        self.reject_unsafe_and_unsupported(root)

        viewBox_str = root.get('viewBox')
        if viewBox_str:
            viewBox = [float(x) for x in re.split(r'[,\s]+', viewBox_str.strip()) if x]
        else:
            w = root.get('width', '24').replace('px', '')
            h = root.get('height', '24').replace('px', '')
            viewBox = [0.0, 0.0, float(w), float(h)]

        ordered_shapes = [] # List of tuples: (path_d, color)

        # Helper to convert fill colors to standard hex
        def normalize_color(color_str):
            color_str = color_str.strip().lower()
            if not color_str or color_str == 'none':
                return None
            if re.match(r'^#[0-9a-f]{6}$', color_str):
                return color_str
            if re.match(r'^#[0-9a-f]{3}$', color_str):
                return '#' + ''.join([c*2 for c in color_str[1:]])
            if color_str == 'black':
                return '#000000'
            if color_str == 'white':
                return '#ffffff'

            raise ValueError(f"Unsupported color format: {color_str}")

        def traverse(element, current_matrix):
            tag = self._strip_ns(element.tag)

            # Update matrix with current element's transform
            transform_str = element.get('transform', '')
            local_matrix = self.parse_transform(transform_str)

            # Combine matrices: current_matrix * local_matrix
            combined_matrix = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
            for i in range(3):
                for j in range(3):
                    for k in range(3):
                        combined_matrix[i][j] += current_matrix[i][k] * local_matrix[k][j]

            SUPPORTED_TAGS = {
                'svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'line', 'polygon', 'polyline', 'defs'
            }

            if tag not in SUPPORTED_TAGS:
                raise ValueError(f"Tag not supported: {tag}")

            # Handle shapes
            if tag in ('path', 'rect', 'circle', 'ellipse', 'line', 'polygon', 'polyline'):
                # Handle strokes explicitly: Visual Lexicon J053 token does not support strokes.
                # If a shape has a stroke that isn't 'none', we must fail closed to avoid data loss.
                stroke = element.get('stroke')
                style = element.get('style', '')
                if not stroke:
                    m = re.search(r'stroke:\s*([^;]+)', style)
                    if m:
                        stroke = m.group(1)

                if stroke and stroke.strip().lower() != 'none':
                    raise ValueError(f"Unsupported feature: stroke in {tag} is not supported by J053 token.")

                d = self.shape_to_path(element)
                if d:
                    transformed_d = self.transform_path(d, combined_matrix)
                    if transformed_d:
                        fill = element.get('fill')
                        if not fill:
                            m = re.search(r'fill:\s*([^;]+)', style)
                            if m:
                                fill = m.group(1)

                        normalized_fill = None
                        if fill:
                            normalized_fill = normalize_color(fill)
                        else:
                            # Default fill is black if not specified (standard SVG behavior)
                            normalized_fill = '#000000'

                        # If fill is explicit 'none', we don't render it since strokes are rejected.
                        if normalized_fill is not None:
                            ordered_shapes.append((transformed_d, normalized_fill))

            for child in element:
                traverse(child, combined_matrix)

        traverse(root, [[1, 0, 0], [0, 1, 0], [0, 0, 1]])

        # Build deduplicated palette and paths, preserving mapping and sequence
        palette_dict = {}
        palette = []

        paths_dict = {}
        paths = []

        shapes = []

        for d, color in ordered_shapes:
            if color not in palette_dict:
                palette_dict[color] = len(palette)
                palette.append(color)
            color_idx = palette_dict[color]

            if d not in paths_dict:
                paths_dict[d] = len(paths)
                paths.append(d)
            path_idx = paths_dict[d]

            # Deduplicate strictly identical sequential shapes
            if not shapes or shapes[-1] != {'path_idx': path_idx, 'color_idx': color_idx}:
                shapes.append({'path_idx': path_idx, 'color_idx': color_idx})

        self.verify_geometry(paths, viewBox)

        token = {
            'concept_id': concept_id,
            'version': 1,
            'viewBox': viewBox,
            'paths': paths,
            'palette': palette,
            'shapes': shapes,
            'semantic_label': semantic_label,
            'alt_text': semantic_label, # Using semantic_label as default alt_text
            'license_evidence': license_evidence,
            'source_hash': source_hash
        }

        # Use existing encode_token if possible, but implementing determinism here
        import json
        import zlib

        serialized = json.dumps(token, separators=(',', ':'), sort_keys=True)
        json_bytes = serialized.encode('utf-8')
        compressed = zlib.compress(json_bytes, level=9)

        MAX_COMPRESSED_SIZE = 2048
        if len(compressed) >= MAX_COMPRESSED_SIZE:
            raise ValueError(f"Token is too large: {len(compressed)} bytes compressed")

        return compressed

    def parse_securely(self, svg_content: str) -> ET.Element:
        """
        Parses SVG content securely, blocking DOCTYPE and ENTITY declarations to prevent XXE,
        and limits size to prevent DOS (Billion Laughs).
        """
        if len(svg_content) > 1024 * 1024: # 1MB limit for raw SVG input
            raise ValueError("SVG content exceeds maximum allowed size of 1MB")

        if re.search(r'<!\s*DOCTYPE', svg_content, re.IGNORECASE) or re.search(r'<!\s*ENTITY', svg_content, re.IGNORECASE):
            raise ValueError("XML Document contains forbidden DOCTYPE or ENTITY declarations")

        parser = ET.XMLParser()
        try:
            root = ET.fromstring(svg_content, parser=parser)
        except ET.ParseError as e:
            raise ValueError(f"Invalid XML: {e}")

        return root
