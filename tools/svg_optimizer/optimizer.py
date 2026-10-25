import re
import xml.etree.ElementTree as ET
from typing import Dict, Any, List

class SvgOptimizer:
    def __init__(self):
        self.unsafe_tags = {'script', 'foreignobject', 'image', 'text', 'use', 'style', 'iframe', 'object'}
        self.unsupported_attrs = {'stroke', 'style'}
        self.unsupported_elements = {'circle', 'rect', 'ellipse', 'polygon', 'polyline', 'arc'}

    def parse_svg(self, svg_str: str) -> ET.Element:
        """Securely parse SVG string into ElementTree, protecting against XXE."""
        if re.search(r'<!DOCTYPE|<!ENTITY', svg_str, re.IGNORECASE):
            raise ValueError("Unsafe XML: DOCTYPE and ENTITY declarations are not allowed")
        try:
            return ET.fromstring(svg_str)
        except Exception as e:
            raise ValueError(f"XML parsing failed: {e}")

    def _remove_namespaces(self, root: ET.Element):
        for el in root.iter():
            if '}' in el.tag:
                el.tag = el.tag.split('}', 1)[1]

    def _quantize_value(self, val: float) -> str:
        """Quantizes floats to save space and normalize coordinates, e.g., 2 decimal places."""
        rounded = round(val, 2)
        if rounded == int(rounded):
            return str(int(rounded))
        return str(rounded)

    def _apply_transform_to_path(self, path_str: str, transform: str) -> str:
        """Evaluates simple nested transforms like translate and scale on path string. Rejects rotate."""
        if not transform:
            return path_str

        if 'rotate' in transform:
            raise ValueError("Unsupported transform: rotate")

        if 'matrix' in transform or 'skew' in transform:
             raise ValueError("Unsupported transform type")

        # Parse translate and scale
        translate_match = re.search(r'translate\s*\(\s*([-\d.]+)(?:[, ]+([-\d.]+))?\s*\)', transform)
        scale_match = re.search(r'scale\s*\(\s*([-\d.]+)(?:[, ]+([-\d.]+))?\s*\)', transform)

        tx, ty = 0.0, 0.0
        sx, sy = 1.0, 1.0

        if translate_match:
            tx = float(translate_match.group(1))
            ty = float(translate_match.group(2)) if translate_match.group(2) else 0.0

        if scale_match:
            sx = float(scale_match.group(1))
            sy = float(scale_match.group(2)) if scale_match.group(2) else sx

        if tx == 0.0 and ty == 0.0 and sx == 1.0 and sy == 1.0:
            return path_str

        # Very simple application to absolute commands M, L. (Ignoring curve control points complexity for scale)
        def repl(match):
             # match is a single number. But to apply transform we need pairs of numbers.
             pass

        # Since writing a full path parser is complex, let's use a simple tokenizer
        tokens = re.findall(r'[A-Za-z]|[-+]?(?:\d*\.\d+|\d+)', path_str)
        transformed_tokens = []
        i = 0
        while i < len(tokens):
             tok = tokens[i]
             if tok.isalpha():
                 transformed_tokens.append(tok)
                 i += 1
             else:
                 if i + 1 < len(tokens) and not tokens[i+1].isalpha():
                      # Pair of coordinates
                      x = float(tokens[i])
                      y = float(tokens[i+1])
                      nx = x * sx + tx
                      ny = y * sy + ty
                      transformed_tokens.append(self._quantize_value(nx))
                      transformed_tokens.append(self._quantize_value(ny))
                      i += 2
                 else:
                      # Single coordinate (e.g. H or V), we don't handle well here. We reject relative commands anyway.
                      # H -> x, V -> y
                      if len(transformed_tokens) > 0:
                          prev_cmd = None
                          for k in range(len(transformed_tokens)-1, -1, -1):
                              if transformed_tokens[k].isalpha():
                                  prev_cmd = transformed_tokens[k]
                                  break
                          if prev_cmd == 'H':
                               x = float(tokens[i])
                               nx = x * sx + tx
                               transformed_tokens.append(self._quantize_value(nx))
                          elif prev_cmd == 'V':
                               y = float(tokens[i])
                               ny = y * sy + ty
                               transformed_tokens.append(self._quantize_value(ny))
                          else:
                               transformed_tokens.append(tokens[i]) # fallback
                      else:
                           transformed_tokens.append(tokens[i])
                      i += 1

        return " ".join(transformed_tokens)

    def _quantize_path(self, path_str: str) -> str:
        """Quantizes coordinates in a path string."""
        if not path_str:
            return ""

        def repl(match):
            return self._quantize_value(float(match.group(0)))

        path_str = re.sub(r'[\s,]+', ' ', path_str.strip())
        quantized = re.sub(r'-?\d+\.?\d*', repl, path_str)
        return quantized

    def _process_element(self, elem: ET.Element, paths: List[str], current_transform: str = None):
        tag = elem.tag.lower()

        if tag in self.unsafe_tags:
            raise ValueError(f"Unsupported element: {tag}")

        if tag in self.unsupported_elements:
            raise ValueError(f"Unsupported element: {tag}")

        for attr in elem.attrib:
            if attr.lower().startswith('on'):
                raise ValueError(f"Unsafe attribute: {attr}")
            if attr.lower() in self.unsupported_attrs:
                raise ValueError(f"Unsupported attribute: {attr}")
            if 'href' in attr.lower():
                val = elem.get(attr)
                if val and (val.startswith('http') or val.startswith('//')):
                     raise ValueError(f"External references not allowed: {val}")

        # Combine parent transform with current transform (simplified)
        elem_transform = elem.get('transform', '')
        transform = " ".join([t for t in [current_transform, elem_transform] if t])

        if tag == 'path':
            d = elem.get('d', '')

            # Explicitly reject relative path commands (lowercase)
            if re.search(r'[mlhvcsqua]', d):
                 raise ValueError("Unsupported relative path commands")

            # Clean and apply transform
            d = self._apply_transform_to_path(d, transform)
            d = self._quantize_path(d)
            if re.match(r'^[MmLlHhVvCcSsQqTtAaZz0-9\s.,-]+$', d):
                paths.append(d)
            else:
                raise ValueError("Path contains invalid characters")

        elif tag == 'line':
            # Convert line to path: M x1 y1 L x2 y2
            x1 = elem.get('x1', '0')
            y1 = elem.get('y1', '0')
            x2 = elem.get('x2', '0')
            y2 = elem.get('y2', '0')
            d = f"M {x1} {y1} L {x2} {y2}"
            d = self._apply_transform_to_path(d, transform)
            d = self._quantize_path(d)
            paths.append(d)

        elif tag in ('g', 'svg', 'defs'):
            for child in elem:
                self._process_element(child, paths, transform)
        else:
             raise ValueError(f"Unsupported geometry element: {tag}")

    def optimize(self, svg_str: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        from tools.visual_lexicon.core import encode_token # Local import to avoid circular issues

        root = self.parse_svg(svg_str)
        self._remove_namespaces(root)

        if root.tag != 'svg':
            raise ValueError("Root element must be svg")

        viewbox_str = root.get('viewBox')
        if not viewbox_str:
            raise ValueError("Missing viewBox")

        try:
            viewbox = [float(x) for x in re.split(r'[\s,]+', viewbox_str.strip())]
            if len(viewbox) != 4:
                raise ValueError()
        except Exception:
            raise ValueError("Invalid viewBox")

        paths = []
        self._process_element(root, paths)

        if not paths:
            raise ValueError("No valid paths found")

        # Deduplicate paths while preserving order
        seen = set()
        deduped_paths = []
        for p in paths:
            if p not in seen:
                seen.add(p)
                deduped_paths.append(p)

        if len(deduped_paths) > 50:
            raise ValueError("Exceeded maximum allowed paths (50)")

        # Create palette, deduplicate colors if provided (fallback to metadata or #000000)
        palette = metadata.get('palette', ['#000000'])
        deduped_palette = list(dict.fromkeys(palette))

        token = {
            'concept_id': metadata.get('concept_id', 'unknown'),
            'version': metadata.get('version', 1),
            'viewBox': viewbox,
            'paths': deduped_paths,
            'palette': deduped_palette,
            'semantic_label': metadata.get('semantic_label', 'unknown'),
        }

        # Preserve license, source and source_hash if present
        for key in ['license', 'source', 'source_hash', 'author']:
             if key in metadata:
                 token[key] = metadata[key]

        # Enforce size limits via J053 core encoding
        try:
            encode_token(token)
        except ValueError as e:
            if "too large" in str(e):
                raise ValueError(f"Optimized token exceeds size limits: {e}")
            else:
                # Other schema validation errors from encode_token
                pass

        return token
