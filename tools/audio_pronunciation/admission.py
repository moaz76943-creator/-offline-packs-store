#!/usr/bin/env python3
"""Admit human pronunciation audio only after canonical ledger and container checks.

A caller-supplied ledger is not evidence. Audio metadata on the candidate is not
a measurement. Unknown metadata is not copied into the accepted record.
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys
from pathlib import Path

MAX_FILE_SIZE = 1024 * 1024  # 1 MB limit
MAX_DURATION_MS = 10000
ALLOWED_SAMPLE_RATES = (16000, 22050, 24000, 32000, 44100, 48000)
MALFORMED = "Invalid file format or malformed header"

# Closed set of candidate fields that may be written to an accepted record.
ALLOWED_FIELDS = (
    "lexeme_id",
    "locale",
    "source_id",
    "human_recorded",
    "is_tts",
    "artifact_path",
    "sha256",
    "format",
    "duration_ms",
    "channels",
    "sample_rate",
)
BANNED_METADATA_KEYS = frozenset({
    "biometric_profile",
    "speaker_age",
    "voiceprint",
    "speaker_id",
    "speaker",
    "speaker_profile",
})

LOCALE_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
LEXEME_ID_RE = re.compile(r"^[a-z][a-z0-9._:-]{2,127}$")

_MPEG1_L3 = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0)
_MPEG1_L2 = (0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, 0)
_MPEG1_L1 = (0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448, 0)
_MPEG2_L3 = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0)
_MPEG2_L1 = (0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256, 0)
_BITRATES = {
    (3, 1): _MPEG1_L3,
    (3, 2): _MPEG1_L2,
    (3, 3): _MPEG1_L1,
    (2, 1): _MPEG2_L3,
    (0, 1): _MPEG2_L3,
    (2, 2): _MPEG2_L3,
    (0, 2): _MPEG2_L3,
    (2, 3): _MPEG2_L1,
    (0, 3): _MPEG2_L1,
}
_SAMPLE_RATES = {
    3: (44100, 48000, 32000),
    2: (22050, 24000, 16000),
    0: (11025, 12000, 8000),
}

_OGG_CRC_TABLE = None
_WEBM_CONTAINERS = frozenset({
    0x1A45DFA3,  # EBML
    0x18538067,  # Segment
    0x1549A966,  # Info
    0x1654AE6B,  # Tracks
    0xAE,        # TrackEntry
    0xE1,        # Audio
    0x1F43B675,  # Cluster
    0xA0,        # BlockGroup
})


def _malformed():
    raise ValueError(MALFORMED)


def sha256_file(path):
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _ogg_crc(data):
    global _OGG_CRC_TABLE
    if _OGG_CRC_TABLE is None:
        table = []
        for index in range(256):
            value = index << 24
            for _ in range(8):
                if value & 0x80000000:
                    value = ((value << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
                else:
                    value = (value << 1) & 0xFFFFFFFF
            table.append(value)
        _OGG_CRC_TABLE = table
    crc = 0
    for byte in data:
        crc = ((crc << 8) ^ _OGG_CRC_TABLE[((crc >> 24) & 0xFF) ^ byte]) & 0xFFFFFFFF
    return crc


def _parse_ogg(data):
    if len(data) < 27 or not data.startswith(b"OggS"):
        _malformed()
    pages = []
    offset = 0
    serial = None
    sequence = 0
    while offset < len(data):
        if offset + 27 > len(data) or data[offset:offset + 4] != b"OggS" or data[offset + 4] != 0:
            _malformed()
        nseg = data[offset + 26]
        header_len = 27 + nseg
        if offset + header_len > len(data):
            _malformed()
        segments = data[offset + 27:header_len + offset]
        body_len = sum(segments)
        page_end = offset + header_len + body_len
        if page_end > len(data):
            _malformed()
        raw = bytearray(data[offset:page_end])
        stored = int.from_bytes(raw[22:26], "little")
        raw[22:26] = b"\x00\x00\x00\x00"
        if _ogg_crc(raw) != stored:
            _malformed()
        page_serial = int.from_bytes(data[offset + 14:offset + 18], "little")
        page_seq = int.from_bytes(data[offset + 18:offset + 22], "little")
        if serial is None:
            serial = page_serial
        elif page_serial != serial or page_seq != sequence:
            _malformed()
        granule = int.from_bytes(data[offset + 6:offset + 14], "little", signed=True)
        pages.append((data[offset + 5], granule, segments, data[offset + header_len:page_end]))
        offset = page_end
        sequence += 1
    if not pages or not (pages[0][0] & 0x02) or not (pages[-1][0] & 0x04):
        _malformed()
    packets = []
    partial = b""
    for _header, _granule, segments, body in pages:
        cursor = 0
        for seg_len in segments:
            if cursor + seg_len > len(body):
                _malformed()
            partial += body[cursor:cursor + seg_len]
            cursor += seg_len
            if seg_len < 255:
                packets.append(partial)
                partial = b""
        if cursor != len(body):
            _malformed()
    if partial or not packets:
        _malformed()
    last_granule = pages[-1][1]
    head = packets[0]
    if head.startswith(b"\x01vorbis") and len(head) >= 16 and int.from_bytes(head[7:11], "little") == 0:
        channels = head[11]
        sample_rate = int.from_bytes(head[12:16], "little")
        audio_packets = [packet for packet in packets if packet[:1] == b"\x00"]
        if channels < 1 or sample_rate < 1 or not audio_packets or last_granule <= 0:
            _malformed()
        duration_ms = (last_granule * 1000 + sample_rate // 2) // sample_rate
    elif head.startswith(b"OpusHead") and len(head) >= 19 and head[8] == 1:
        channels = head[9]
        pre_skip = int.from_bytes(head[10:12], "little")
        if channels < 1 or pre_skip > last_granule:
            _malformed()
        audio_packets = [packet for packet in packets[1:] if not packet.startswith((b"OpusHead", b"OpusTags"))]
        if not audio_packets:
            _malformed()
        sample_rate = 48000
        samples = last_granule - pre_skip
        if samples <= 0:
            _malformed()
        duration_ms = (samples * 1000 + sample_rate // 2) // sample_rate
    else:
        _malformed()
    if duration_ms <= 0:
        _malformed()
    return {"duration_ms": duration_ms, "channels": channels, "sample_rate": sample_rate}


def _parse_wav(data):
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        _malformed()
    riff_size = struct.unpack_from("<I", data, 4)[0]
    if riff_size < 4 or riff_size + 8 != len(data):
        _malformed()
    offset = 12
    end = 8 + riff_size
    fmt = None
    data_size = None
    while offset + 8 <= end:
        chunk_id = data[offset:offset + 4]
        chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
        offset += 8
        if offset + chunk_size > end:
            _malformed()
        if chunk_id == b"fmt ":
            if chunk_size < 16:
                _malformed()
            audio_format, channels, sample_rate, byte_rate, block_align, bits = struct.unpack_from(
                "<HHIIHH", data, offset)
            align = channels * (bits // 8) if bits in (8, 16, 24, 32) else 0
            if (audio_format != 1 or channels < 1 or sample_rate < 1 or align == 0
                    or block_align != align or byte_rate != sample_rate * block_align):
                _malformed()
            fmt = (channels, sample_rate, byte_rate, block_align)
        elif chunk_id == b"data":
            if data_size is not None:
                _malformed()
            data_size = chunk_size
        offset += chunk_size
        if chunk_size % 2 == 1:
            if offset >= end:
                _malformed()
            offset += 1
    if offset != end or fmt is None or not data_size:
        _malformed()
    channels, sample_rate, byte_rate, block_align = fmt
    if data_size % block_align != 0:
        _malformed()
    duration_ms = (data_size * 1000 + byte_rate // 2) // byte_rate
    if duration_ms <= 0:
        _malformed()
    return {"duration_ms": duration_ms, "channels": channels, "sample_rate": sample_rate}


def _xing_offset(version, mode):
    if version == 3:
        return 36 if mode != 3 else 21
    return 21 if mode != 3 else 13


def _parse_mp3(data):
    offset = 0
    if data.startswith(b"ID3"):
        if len(data) < 10 or data[3] > 4 or data[5] & 0x7F:
            _malformed()
        size = ((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14) | ((data[8] & 0x7F) << 7) | (data[9] & 0x7F)
        offset = 10 + size
        if offset > len(data):
            _malformed()
    end = len(data) - 128 if len(data) >= 128 and data[-128:-125] == b"TAG" else len(data)
    frames = 0
    audio_samples = 0
    sample_rate = None
    channels = None
    while offset + 4 <= end:
        b0, b1, b2, b3 = data[offset:offset + 4]
        if b0 != 0xFF or (b1 & 0xE0) != 0xE0:
            _malformed()
        version = (b1 >> 3) & 0x03
        layer = (b1 >> 1) & 0x03
        bitrate_index = (b2 >> 4) & 0x0F
        rate_index = (b2 >> 2) & 0x03
        padding = (b2 >> 1) & 0x01
        mode = (b3 >> 6) & 0x03
        if version == 1 or layer == 0 or rate_index == 3 or bitrate_index in (0, 15):
            _malformed()
        if (version, layer) not in _BITRATES:
            _malformed()
        bitrate = _BITRATES[(version, layer)][bitrate_index] * 1000
        rate = _SAMPLE_RATES[version][rate_index]
        if layer == 3:
            frame_len = ((12 * bitrate // rate) + padding) * 4
            samples = 384
        elif version == 3 or layer != 1:
            frame_len = (144 * bitrate // rate) + padding
            samples = 1152
        else:
            frame_len = (72 * bitrate // rate) + padding
            samples = 576
        if frame_len < 4 or offset + frame_len > end:
            _malformed()
        frame_channels = 1 if mode == 3 else 2
        if sample_rate is None:
            sample_rate = rate
            channels = frame_channels
        elif sample_rate != rate or channels != frame_channels:
            _malformed()
        marker_at = _xing_offset(version, mode)
        header_frame = data[offset + marker_at:offset + marker_at + 4] in (b"Xing", b"Info")
        frames += 1
        if not header_frame:
            audio_samples += samples
        offset += frame_len
    if offset != end or frames < 1 or audio_samples <= 0 or not sample_rate or not channels:
        _malformed()
    duration_ms = (audio_samples * 1000 + sample_rate // 2) // sample_rate
    if duration_ms <= 0:
        _malformed()
    return {"duration_ms": duration_ms, "channels": channels, "sample_rate": sample_rate}


def _vint(data, offset, keep_marker):
    if offset >= len(data) or data[offset] == 0:
        _malformed()
    mask = 0x80
    length = 1
    while data[offset] & mask == 0:
        mask >>= 1
        length += 1
        if mask == 0 or offset + length > len(data):
            _malformed()
    raw = int.from_bytes(data[offset:offset + length], "big")
    if keep_marker:
        return raw, offset + length
    value = raw & ((1 << (7 * length)) - 1)
    if value == (1 << (7 * length)) - 1:
        return None, offset + length
    return value, offset + length


def _parse_elements(data, start, end):
    elements = []
    offset = start
    while offset < end:
        element_id, offset = _vint(data, offset, True)
        size, offset = _vint(data, offset, False)
        if size is None:
            body_end = end
        else:
            body_end = offset + size
            if body_end > end:
                _malformed()
        if element_id in _WEBM_CONTAINERS:
            elements.append((element_id, _parse_elements(data, offset, body_end)))
        else:
            elements.append((element_id, data[offset:body_end]))
        offset = body_end
    if offset != end:
        _malformed()
    return elements


def _child(elements, element_id):
    for found, payload in elements:
        if found == element_id:
            return payload
    return None


def _children(elements, element_id):
    return [payload for found, payload in elements if found == element_id]


def _uint(blob):
    if not isinstance(blob, (bytes, bytearray)) or not blob or len(blob) > 8:
        _malformed()
    return int.from_bytes(blob, "big")


def _float(blob):
    if len(blob) == 4:
        return struct.unpack(">f", blob)[0]
    if len(blob) == 8:
        return struct.unpack(">d", blob)[0]
    _malformed()


def _integer_rate(value):
    if isinstance(value, float):
        if abs(value - round(value)) > 1e-3:
            _malformed()
        value = int(round(value))
    if not isinstance(value, int) or value <= 0:
        _malformed()
    return value


def _block_time(payload):
    if not payload:
        _malformed()
    mask = 0x80
    length = 1
    while payload[0] & mask == 0:
        mask >>= 1
        length += 1
        if mask == 0:
            _malformed()
    if len(payload) < length + 4:
        _malformed()
    return int.from_bytes(payload[length:length + 2], "big", signed=True)


def _cluster_times(elements, scale):
    times = []
    timestamp = _child(elements, 0xE7)
    if timestamp is None:
        _malformed()
    cluster_ts = _uint(timestamp)
    for element_id, payload in elements:
        if element_id in (0xA1, 0xA3):
            times.append(cluster_ts + _block_time(payload))
        elif element_id == 0xA0:
            for block in _children(payload, 0xA1):
                times.append(cluster_ts + _block_time(block))
    if scale <= 0:
        _malformed()
    return [(tick * scale + 500_000) // 1_000_000 for tick in times]


def _parse_webm(data):
    if len(data) < 8 or not data.startswith(b"\x1a\x45\xdf\xa3"):
        _malformed()
    elements = _parse_elements(data, 0, len(data))
    ebml = _child(elements, 0x1A45DFA3)
    segment = _child(elements, 0x18538067)
    if not isinstance(ebml, list) or not isinstance(segment, list):
        _malformed()
    doctype = _child(ebml, 0x4282)
    if doctype not in (b"webm", b"matroska"):
        _malformed()
    info = _child(segment, 0x1549A966)
    tracks = _child(segment, 0x1654AE6B)
    if not isinstance(info, list) or not isinstance(tracks, list):
        _malformed()
    scale_blob = _child(info, 0x2AD7B1)
    scale = _uint(scale_blob) if scale_blob is not None else 1_000_000
    duration_units = _child(info, 0x4489)
    declared_ms = None
    if duration_units is not None:
        declared_ms = int(round(_float(duration_units) * scale / 1_000_000))
    audio = []
    for entry in _children(tracks, 0xAE):
        if _uint(_child(entry, 0x83) or b"") != 2:
            continue
        codec = _child(entry, 0x86)
        audio_el = _child(entry, 0xE1)
        if not isinstance(codec, (bytes, bytearray)) or not codec.startswith(b"A_") or not isinstance(audio_el, list):
            _malformed()
        channels_blob = _child(audio_el, 0x9F)
        rate_blob = _child(audio_el, 0xB5)
        if channels_blob is None or rate_blob is None:
            _malformed()
        audio.append((_uint(channels_blob), _integer_rate(_float(rate_blob))))
    if len(audio) != 1:
        _malformed()
    channels, sample_rate = audio[0]
    times = []
    for cluster in _children(segment, 0x1F43B675):
        times.extend(_cluster_times(cluster, scale))
    if not times or channels < 1:
        _malformed()
    span_ms = max(times)
    duration_ms = span_ms if declared_ms is None else max(span_ms, declared_ms)
    if duration_ms <= 0:
        _malformed()
    return {"duration_ms": duration_ms, "channels": channels, "sample_rate": sample_rate}


def inspect_audio(data, format_hint):
    """Parse a container and measure duration, channels, and sample rate."""
    if format_hint == "wav":
        return _parse_wav(data)
    if format_hint == "mp3":
        return _parse_mp3(data)
    if format_hint == "ogg":
        return _parse_ogg(data)
    if format_hint == "webm":
        return _parse_webm(data)
    _malformed()


def _verified_sources():
    try:
        from tools.contribution_gate.evidence import verified_sources
        return verified_sources
    except ImportError:
        repo = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(repo))
        from tools.contribution_gate.evidence import verified_sources
        return verified_sources


def source_is_approved(source_id, ledger_data, root_dir):
    """Require the canonical ledger checks, not a shallow source_id/kind/status row."""
    try:
        sources = _verified_sources()(ledger_data, root_dir)
    except ValueError:
        return False
    src = sources.get(source_id)
    return (isinstance(src, dict)
            and src.get("kind") == "pronunciation"
            and src.get("status") == "APPROVED_FOR_REDISTRIBUTION")


def _banned_metadata(value):
    if isinstance(value, dict):
        return any(key in BANNED_METADATA_KEYS or _banned_metadata(inner) for key, inner in value.items())
    if isinstance(value, list):
        return any(_banned_metadata(inner) for inner in value)
    return False


def _require_allowlisted(entry):
    if _banned_metadata(entry):
        raise ValueError("Biometric/personal metadata not allowed")
    unknown = [key for key in entry if key not in ALLOWED_FIELDS]
    if unknown:
        raise ValueError("Unknown metadata fields not allowed")
    for key in ALLOWED_FIELDS:
        if key in entry and isinstance(entry[key], (dict, list)):
            raise ValueError("Unknown metadata fields not allowed")


def _public_record(entry, measured):
    record = {}
    for key in ALLOWED_FIELDS:
        if key in entry and key not in ("duration_ms", "channels", "sample_rate"):
            record[key] = entry[key]
    record["duration_ms"] = measured["duration_ms"]
    record["channels"] = measured["channels"]
    record["sample_rate"] = measured["sample_rate"]
    return record


def _quarantine_record(entry, reason):
    safe = {"rejection_reason": str(reason)}
    if isinstance(entry, dict):
        for key in ("lexeme_id", "locale", "source_id", "artifact_path"):
            value = entry.get(key)
            if isinstance(value, str):
                safe[key] = value
    return safe


def _require_declaration(entry, key, measured, missing_message):
    if entry.get(key) != measured:
        raise ValueError(missing_message)


def process_candidates(candidates, ledger, root_dir):
    accepted = []
    rejected = []

    for entry in candidates:
        try:
            if not isinstance(entry, dict):
                raise ValueError("Invalid candidate")
            _require_allowlisted(entry)

            lexeme_id = entry.get("lexeme_id", "")
            locale = entry.get("locale", "")
            source_id = entry.get("source_id", "")
            if not isinstance(lexeme_id, str) or not LEXEME_ID_RE.match(lexeme_id):
                raise ValueError("Invalid lexeme_id")
            if not isinstance(locale, str) or not LOCALE_RE.match(locale):
                raise ValueError("Invalid locale")
            if not source_is_approved(source_id, ledger, root_dir):
                raise ValueError("Source rights missing or unapproved")

            if entry.get("human_recorded") is not True:
                raise ValueError("Must be human_recorded")
            if entry.get("is_tts") is True:
                raise ValueError("TTS is not allowed")

            artifact_path = entry.get("artifact_path", "")
            if not isinstance(artifact_path, str) or artifact_path.startswith(("http://", "https://")):
                raise ValueError("Remote audio not allowed")
            root = Path(root_dir).resolve()
            full_path = (root / artifact_path).resolve()
            if not full_path.is_relative_to(root):
                raise ValueError("Path escapes root")
            if not full_path.is_file():
                raise ValueError("File does not exist")
            size = os.path.getsize(full_path)
            if size > MAX_FILE_SIZE:
                raise ValueError("File too large")

            expected_sha = entry.get("sha256")
            actual_sha = sha256_file(full_path)
            if actual_sha != expected_sha:
                raise ValueError("SHA256 mismatch")

            data = full_path.read_bytes()
            if len(data) != size:
                raise ValueError(MALFORMED)
            measured = inspect_audio(data, entry.get("format", "ogg"))
            if measured["duration_ms"] > MAX_DURATION_MS:
                raise ValueError("Audio duration too long")
            _require_declaration(entry, "duration_ms", measured["duration_ms"], "missing or contradictory duration")
            if measured["channels"] > 2:
                raise ValueError("Too many channels")
            _require_declaration(entry, "channels", measured["channels"], "missing or contradictory channels")
            if measured["sample_rate"] not in ALLOWED_SAMPLE_RATES:
                raise ValueError("Unsupported sample rate")
            _require_declaration(entry, "sample_rate", measured["sample_rate"], "missing or contradictory sample rate")
            accepted.append(_public_record(entry, measured))
        except ValueError as exc:
            rejected.append(_quarantine_record(entry, exc))

    accepted.sort(key=lambda row: (row.get("lexeme_id", ""), row.get("locale", "")))
    return accepted, rejected


def main():
    parser = argparse.ArgumentParser(description="Audio Pronunciation Admission Gate")
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--quarantine", required=True, type=Path)
    parser.add_argument("--repo-root", default=".", type=Path)
    args = parser.parse_args()

    try:
        with open(args.ledger, "r", encoding="utf-8") as handle:
            ledger_data = json.load(handle)
    except Exception as exc:
        print(f"Error reading ledger: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(args.input, "r", encoding="utf-8") as handle:
            candidates = [json.loads(line) for line in handle if line.strip()]
    except Exception as exc:
        print(f"Error reading input: {exc}", file=sys.stderr)
        sys.exit(1)

    accepted, rejected = process_candidates(candidates, ledger_data, args.repo_root)

    try:
        with open(args.output, "w", encoding="utf-8") as handle:
            for item in accepted:
                handle.write(json.dumps(item, separators=(",", ":")) + "\n")
        with open(args.quarantine, "w", encoding="utf-8") as handle:
            for item in rejected:
                handle.write(json.dumps(item, separators=(",", ":")) + "\n")
    except Exception as exc:
        print(f"Error writing output/quarantine: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
