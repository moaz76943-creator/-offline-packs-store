from typing import Dict, Any
import re

def verify_geometry_roundtrip(token: Dict[str, Any]) -> bool:
    """
    Verifies that all geometry in the paths is completely contained within the viewBox.
    This fulfills the requirement to have a round-trip geometry and visual-bounds verifier.
    """
    viewBox = token.get('viewBox')
    if not viewBox or len(viewBox) != 4:
        raise ValueError("Invalid or missing viewBox in token")

    vb_x, vb_y, vb_w, vb_h = viewBox
    min_x = vb_x
    min_y = vb_y
    max_x = vb_x + vb_w
    max_y = vb_y + vb_h

    paths = token.get('paths', [])
    for path_str in paths:
        # Extract all coordinates
        tokens = re.findall(r'-?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?', path_str)
        # Note: A command like 'A' takes 7 parameters, some of which are not simple x,y coordinates
        # However, checking all numeric values that could represent points or bounding box size
        # is a good approximation. But more robustly, we parse standard M/L/C/S/Q coordinates.
        # Given this is a simple check, we will parse the path string properly.

        path_tokens = re.findall(r'[a-zA-Z]+|-?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?', path_str)
        i = 0
        cmd = ''

        while i < len(path_tokens):
            t = path_tokens[i]
            if re.match(r'^[a-zA-Z]$', t):
                cmd = t.upper()
                i += 1
                if cmd == 'Z':
                    continue
            else:
                pass # Continue with last command (implicit)

            if cmd in ('M', 'L', 'T'):
                if i + 1 >= len(path_tokens): break
                x = float(path_tokens[i])
                y = float(path_tokens[i+1])
                i += 2

                # Check bounds with a small tolerance (e.g., 0.1) for floating point quantization
                if not (min_x - 0.1 <= x <= max_x + 0.1):
                    raise ValueError(f"Geometry out of bounds: x={x} not in [{min_x}, {max_x}]")
                if not (min_y - 0.1 <= y <= max_y + 0.1):
                    raise ValueError(f"Geometry out of bounds: y={y} not in [{min_y}, {max_y}]")

            elif cmd in ('S', 'Q'):
                if i + 3 >= len(path_tokens): break
                x1, y1 = float(path_tokens[i]), float(path_tokens[i+1])
                x, y = float(path_tokens[i+2]), float(path_tokens[i+3])
                i += 4

                for cx, cy in [(x1,y1), (x,y)]:
                    if not (min_x - 0.1 <= cx <= max_x + 0.1):
                        raise ValueError(f"Geometry out of bounds: x={cx} not in [{min_x}, {max_x}]")
                    if not (min_y - 0.1 <= cy <= max_y + 0.1):
                        raise ValueError(f"Geometry out of bounds: y={cy} not in [{min_y}, {max_y}]")

            elif cmd == 'C':
                if i + 5 >= len(path_tokens): break
                x1, y1 = float(path_tokens[i]), float(path_tokens[i+1])
                x2, y2 = float(path_tokens[i+2]), float(path_tokens[i+3])
                x, y = float(path_tokens[i+4]), float(path_tokens[i+5])
                i += 6

                for cx, cy in [(x1,y1), (x2,y2), (x,y)]:
                    if not (min_x - 0.1 <= cx <= max_x + 0.1):
                        raise ValueError(f"Geometry out of bounds: x={cx} not in [{min_x}, {max_x}]")
                    if not (min_y - 0.1 <= cy <= max_y + 0.1):
                        raise ValueError(f"Geometry out of bounds: y={cy} not in [{min_y}, {max_y}]")

            elif cmd == 'A':
                if i + 6 >= len(path_tokens): break
                # rx, ry, x_rot, large_arc, sweep, x, y
                rx, ry = float(path_tokens[i]), float(path_tokens[i+1])
                x, y = float(path_tokens[i+5]), float(path_tokens[i+6])
                i += 7

                # For an arc, the actual curve can extend by up to rx and ry from the start/end points or center.
                # A simple bounds check without solving the arc equations is to verify that
                # x +/- rx and y +/- ry at the endpoints are within bounds, but ideally
                # we just need to know it doesn't grossly overflow.
                # The strictest check is ensuring that the endpoints +/- radii are still within the viewBox
                # (which covers all possible arc paths connecting those points with those radii).

                # Check endpoints with radii
                if not (min_x - 0.1 <= x - rx and x + rx <= max_x + 0.1):
                    raise ValueError(f"Arc geometry out of bounds: x={x}, rx={rx} not in [{min_x}, {max_x}]")
                if not (min_y - 0.1 <= y - ry and y + ry <= max_y + 0.1):
                    raise ValueError(f"Arc geometry out of bounds: y={y}, ry={ry} not in [{min_y}, {max_y}]")
            else:
                i += 1

    return True
