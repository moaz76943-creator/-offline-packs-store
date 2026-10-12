"""CVT1: intentionally tiny, offline, fail-closed SVG subset -> ASCII token.

Wire: b'CVT1:' + RFC4648 urlsafe-base64(zlib(level=9, canonical UTF-8 JSON)).
JSON: [1, [[kind, geometry, fill, stroke, stroke_width], ...]].
kind: p=path, r=rectangle, c=circle, l=line, g=polygon, y=polyline.
Coordinates are in the fixed 0..24 viewBox and are quantized to 0.1.
No implicit SVG semantics beyond the explicitly supported paint attributes.
"""
import base64
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape
import json
import re
import xml.etree.ElementTree as ET
import zlib

PREFIX = b'CVT1:'
MAX_BYTES = 2047  # strictly fewer than 2048 bytes
MAX_JSON = 8192
MAX_ELEMENTS = 24
MAX_PATH_COMMANDS = 64
MAX_SOURCE = 32768
NUM = re.compile(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)\Z')
TOKEN = re.compile(r'[MLCQZ]|[-+]?(?:\d+(?:\.\d*)?|\.\d+)')
SVG_NS = 'http://www.w3.org/2000/svg'
GEOMETRY = {
    'path': ('p', ('d',)), 'rect': ('r', ('x', 'y', 'width', 'height')),
    'circle': ('c', ('cx', 'cy', 'r')), 'line': ('l', ('x1', 'y1', 'x2', 'y2')),
    'polygon': ('g', ('points',)), 'polyline': ('y', ('points',)),
}
PAINT = {'fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin'}
ARITY = {'M': 2, 'L': 2, 'Q': 4, 'C': 6, 'Z': 0}


class VectorError(ValueError):
    """Invalid, ambiguous, oversized or unsafe media input."""


def number(raw, *, max_value=24):
    if not isinstance(raw, str) or not NUM.fullmatch(raw.strip()):
        raise VectorError('invalid decimal coordinate')
    try:
        n = Decimal(raw.strip())
        if not n.is_finite() or n < 0 or n > max_value:
            raise VectorError('coordinate outside safe viewBox')
        n = n.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise VectorError('invalid coordinate') from exc
    return format(n, 'f').rstrip('0').rstrip('.') if '.' in format(n, 'f') else format(n, 'f')


def normalize_path(path):
    if not isinstance(path, str) or len(path) > 1024:
        raise VectorError('path too long')
    parts = TOKEN.findall(path)
    if not re.fullmatch(r'[\s,]*', TOKEN.sub('', path)) or not parts:
        raise VectorError('unsupported path command or lexical payload')
    i, commands, out = 0, 0, []
    while i < len(parts):
        command = parts[i]
        if command not in ARITY or (commands == 0 and command != 'M'):
            raise VectorError('explicit absolute path commands required')
        i += 1
        n = ARITY[command]
        if i + n > len(parts) or any(p in ARITY for p in parts[i:i + n]):
            raise VectorError('malformed path arguments')
        coords = [number(p) for p in parts[i:i + n]]
        i += n
        commands += 1
        if commands > MAX_PATH_COMMANDS:
            raise VectorError('too many path commands')
        out.append(command + (' '.join(coords) if coords else ''))
    if commands < 2:
        raise VectorError('path has no drawable geometry')
    return ''.join(out)


def _points(raw):
    parts = re.findall(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)', raw)
    if not re.fullmatch(r'[\s,]*', re.sub(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)', '', raw)):
        raise VectorError('invalid polygon syntax')
    if len(parts) < 4 or len(parts) % 2 or len(parts) > 64:
        raise VectorError('invalid polygon vertices')
    return ' '.join(number(p) for p in parts)


def _paint(node):
    fill = node.attrib.get('fill', 'none').lower()
    stroke = node.attrib.get('stroke', '#172b4d').lower()
    if any(not re.fullmatch(r'none|#[0-9a-f]{6}', value) for value in (fill, stroke)):
        raise VectorError('paint must be #rrggbb or none')
    if fill == stroke == 'none':
        raise VectorError('invisible shape')
    width = number(node.attrib.get('stroke-width', '2'), max_value=4)
    if stroke != 'none' and not 1 <= float(width) <= 4:
        raise VectorError('stroke too thin to be legible')
    if node.attrib.get('stroke-linecap', 'round') != 'round' or node.attrib.get('stroke-linejoin', 'round') != 'round':
        raise VectorError('only round joins/caps supported')
    return [fill, stroke, width]


def _parse_svg(source):
    if isinstance(source, str):
        source = source.encode('utf-8')
    if not isinstance(source, bytes) or len(source) > MAX_SOURCE or b'\x00' in source:
        raise VectorError('invalid source size or encoding')
    # ElementTree does not fetch external entities, but forbid ALL declarations and PIs.
    if re.search(rb'<!|<\?|&|\]\]>', source, re.IGNORECASE):
        raise VectorError('XML entities/declarations/processing instructions forbidden')
    try:
        root = ET.fromstring(source)
    except (ET.ParseError, UnicodeError) as exc:
        raise VectorError('invalid SVG XML') from exc

    def local(tag):
        if not isinstance(tag, str):
            raise VectorError('non-element SVG node')
        if tag.startswith('{'):
            ns, sep, name = tag[1:].partition('}')
            if ns != SVG_NS or not sep:
                raise VectorError('unexpected XML namespace')
            return name
        return tag

    if local(root.tag) != 'svg' or len(root) > MAX_ELEMENTS:
        raise VectorError('expected compact SVG root')
    if set(root.attrib) - {'viewBox', 'xmlns', 'width', 'height'}:
        raise VectorError('unsafe root attributes')
    if root.attrib.get('viewBox') != '0 0 24 24':
        raise VectorError('only 24x24 coordinate space supported')
    if root.attrib.get('width', '24') not in ('24', '24px') or root.attrib.get('height', '24') not in ('24', '24px'):
        raise VectorError('unexpected SVG dimensions')
    if root.text and root.text.strip():
        raise VectorError('text elements forbidden')
    shapes = []
    for node in root:
        name = local(node.tag)
        if name not in GEOMETRY or list(node) or (node.text and node.text.strip()) or (node.tail and node.tail.strip()):
            raise VectorError('unsupported SVG element or nested content')
        kind, attrs = GEOMETRY[name]
        if set(node.attrib) - set(attrs) - PAINT or any(a not in node.attrib for a in attrs):
            raise VectorError('invalid or executable SVG attribute')
        if kind == 'p':
            geo = normalize_path(node.attrib['d'])
        elif kind in ('g', 'y'):
            geo = _points(node.attrib['points'])
        else:
            geo = ' '.join(number(node.attrib[a]) for a in attrs)
            values = [float(number(node.attrib[a])) for a in attrs]
            if kind == 'r' and (not values[2] or not values[3] or values[0]+values[2] > 24 or values[1]+values[3] > 24):
                raise VectorError('rectangle outside viewBox')
            if kind == 'c' and (not values[2] or values[0]-values[2] < 0 or values[1]-values[2] < 0 or values[0]+values[2] > 24 or values[1]+values[2] > 24):
                raise VectorError('circle outside viewBox')
        shapes.append([kind, geo] + _paint(node))
    if not shapes:
        raise VectorError('empty vector')
    return shapes


def _canonical(shapes):
    return json.dumps([1, shapes], ensure_ascii=True, separators=(',', ':')).encode('ascii')


def compile_svg(source, limit=MAX_BYTES):
    if not isinstance(limit, int) or not 0 < limit <= MAX_BYTES:
        raise VectorError('invalid token budget')
    payload = _canonical(_parse_svg(source))
    if len(payload) > MAX_JSON:
        raise VectorError('geometry exceeds decode budget')
    token = PREFIX + base64.urlsafe_b64encode(zlib.compress(payload, level=9))
    if len(token) > limit:
        raise VectorError('compressed token exceeds budget')
    if _canonical(decode_token(token)) != payload:
        raise VectorError('round-trip integrity failed')
    return token


def decode_token(token):
    if not isinstance(token, bytes) or not token.startswith(PREFIX) or len(token) > MAX_BYTES:
        raise VectorError('invalid CVT1 token header or size')
    encoded = token[len(PREFIX):]
    if not encoded or not re.fullmatch(rb'[A-Za-z0-9_-]+={0,2}', encoded):
        raise VectorError('invalid base64 token')
    try:
        data = base64.urlsafe_b64decode(encoded)
        if base64.urlsafe_b64encode(data) != encoded:
            raise VectorError('noncanonical base64')
        decoder = zlib.decompressobj()
        payload = decoder.decompress(data, MAX_JSON + 1)
        if len(payload) > MAX_JSON or decoder.unconsumed_tail or not decoder.eof or decoder.unused_data:
            raise VectorError('decompression budget exceeded')
        body = json.loads(payload)
        if not isinstance(body, list) or len(body) != 2 or body[0] != 1 or not isinstance(body[1], list):
            raise VectorError('invalid token schema')
        shapes = body[1]
        if not 1 <= len(shapes) <= MAX_ELEMENTS:
            raise VectorError('invalid token shape count')
        # Enforce identical shape grammar on decode: never render untrusted JSON directly.
        for shape in shapes:
            if not isinstance(shape, list) or len(shape) != 5 or shape[0] not in {'p','r','c','l','g','y'}:
                raise VectorError('invalid token geometry')
            kind, geo, fill, stroke, width = shape
            if not all(isinstance(x, str) for x in shape[1:]):
                raise VectorError('invalid token field types')
            if kind == 'p':
                if normalize_path(geo) != geo:
                    raise VectorError('noncanonical path')
            elif kind in ('g', 'y'):
                if _points(geo) != geo:
                    raise VectorError('noncanonical vertices')
            else:
                expected = {'r':4,'c':3,'l':4}[kind]
                parts = geo.split(' ')
                if len(parts) != expected or ' '.join(number(p) for p in parts) != geo:
                    raise VectorError('invalid token coordinates')
                nums = list(map(float, parts))
                if kind == 'r' and (nums[2] <= 0 or nums[3] <= 0 or nums[0]+nums[2] > 24 or nums[1]+nums[3] > 24):
                    raise VectorError('bad rectangle')
                if kind == 'c' and (nums[2] <= 0 or nums[0]-nums[2] < 0 or nums[1]-nums[2] < 0 or nums[0]+nums[2] > 24 or nums[1]+nums[2] > 24):
                    raise VectorError('bad circle')
            if any(not re.fullmatch(r'none|#[0-9a-f]{6}', x) for x in (fill, stroke)) or fill == stroke == 'none':
                raise VectorError('invalid token paint')
            if number(width, max_value=4) != width or (stroke != 'none' and not 1 <= float(width) <= 4):
                raise VectorError('bad stroke width')
        if payload != _canonical(shapes) or token != PREFIX + base64.urlsafe_b64encode(zlib.compress(payload, 9)):
            raise VectorError('noncanonical compressed representation')
        return shapes
    except (ValueError, zlib.error, UnicodeError, json.JSONDecodeError) as exc:
        raise VectorError('invalid compressed vector') from exc


def render_svg(token, fallback_label):
    if not isinstance(fallback_label, str) or not fallback_label.strip() or len(fallback_label) > 120:
        raise VectorError('accessible fallback label required')
    parts = [f'<svg xmlns="{SVG_NS}" viewBox="0 0 24 24" role="img" aria-label="{escape(fallback_label, quote=True)}">']
    attr = {'p': ('path', ('d',)), 'r': ('rect', ('x','y','width','height')),
            'c': ('circle', ('cx','cy','r')), 'l': ('line', ('x1','y1','x2','y2')),
            'g': ('polygon', ('points',)), 'y': ('polyline', ('points',))}
    for kind, geometry, fill, stroke, width in decode_token(token):
        name, names = attr[kind]
        if kind in ('p','g','y'):
            coords = f'{names[0]}="{geometry}"'
        else:
            coords = ' '.join(f'{key}="{value}"' for key, value in zip(names, geometry.split(' ')))
        parts.append(f'<{name} {coords} fill="{fill}" stroke="{stroke}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/>')
    parts.append('</svg>')
    return ''.join(parts)
