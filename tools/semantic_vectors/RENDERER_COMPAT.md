# CVT1 renderer and decoder compatibility contract v1

**Status: BLOCKED**. Samples in `media/semantic_vectors/fixtures/` are
non-distributable test fixtures until the app's actual offline decoder passes
this exact contract. Do not add them to the root `manifest.json`, CDN/PAD,
store-index, runtime downloads, or production catalog before that proof.

1. Read the ASCII token; enforce `len(token) < 2048`, `CVT1:` header, strict
   canonical RFC4648 URL-safe Base64 including `=` padding.
2. Inflate RFC1950 zlib to a maximum of 8192 decoded bytes, rejecting trailing
   data, truncation, decompression bombs, and non-canonical re-compression.
3. Decode UTF-8 JSON `[1, shapes]`; each shape is five strings/fields:
   `[kind, geometry, fill, stroke, strokeWidth]` with kind `p`, `r`, `c`,
   `l`, `g`, `y` (path, rect, circle, line, polygon, polyline).
4. Validate all geometry using the same bounds as `compact.py`, fixed 24x24
   viewBox and 0.1 coordinate quantum. Paths: explicit absolute M/L/Q/C/Z
   commands only; max 64 commands and max 24 primitives.
5. Render strokes in device-independent 24x24 space with round caps/joins.
   Colors are six-digit hex or `none`; strokes must be 1..4 units wide.
   No fonts, external assets, XML script parsing, network requests or fallback
   that fetches remote content. Use a localized label by `concept_id` from
   the manifest; fall back to the English label without text inside artwork.
6. Golden tests for each SHA-256-addressed fixture: app decoder must produce
   identical `shapes` data to the Python `decode_token` and rasterize at
   24x24, 36x36, and 48x48 px with no clipping, visible outline/solid shape,
   and readable semantic identity on actual low-density small screens.
7. Negative tests: tampered hash, invalid Base64, zlib bomb/trailing bytes,
   unknown kind, out-of-bounds coordinates, invalid/invisible paint, HTML/XML
   payloads or any over-budget token MUST fail closed.
8. App publishes a versioned decoder capability result (device/OS/backend,
   app commit SHA, token schema, fixture SHAs, golden result and human small-
   screen inspection). Only **then** can a separate reviewed release change
   set `decoder_compatibility.verified=true` and `release_status=approved`.
   This repository's sample compiler never does this automatically.

Test command: `python3 -m unittest discover -s tools/semantic_vectors -p 'test_*.py' -v`.
No private app code or screenshots belong in this public repo.
