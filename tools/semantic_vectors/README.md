# Semantic compact vectors — public offline fixtures

A strict stdlib-only CVT1 encoder/decoder and append-only build pipeline, for
five **original** public 24x24 SVG examples. These are illustrations of
**concepts/senses**, not labels tied to a particular language. A token is
referenced once by a stable `concept_id` and has explicit language-specific
labels/lexeme bindings; homographs remain distinct by `sense_id`.

```
python3 -m unittest discover -s tools/semantic_vectors -p 'test_*.py' -v
python3 -m compileall -q tools/semantic_vectors
python3 tools/semantic_vectors/build.py --root media/semantic_vectors --day 2026-10-12
```

Workflow for daily additions: author a new small SVG using supported geometry
and explicit paint, add a **new** `concept_id` and specific `sense_id` with
language mappings, cite its verifiable CC0/original authorship in
`provenance.json` with a SHA-256-matched evidence file, and list that SVG's
SHA-256 in the same rights record's `bound_source_sha256`. Reusing a provenance
id does not cover any other file. Then run the build with
the day's date. The builder validates every declared item before writing,
never deletes existing fixtures, refuses mutation of approved concepts, and
publishes the manifest **last** via atomic replace. Repeat with unchanged
inputs and the manifest is byte-identical. Adding new items is incremental;
any changed artwork for an existing ID requires an explicit reviewed version
migration rather than overwriting the identifier.

**File policy:** do not modify the public root `manifest.json` or enable a
runtime distribution path here. Current manifest has `decoder_pending` and is
not ready for application use. The sample token files are decoder **fixtures**.

Security: script/style/link/image/font/foreignObject/event handlers, XML
entities, external resources, SVG transforms, non-whitelisted attributes,
out-of-range or overly complex geometry, and compressed output >=2048 bytes
are rejected. Only a small supported SVG subset can be accepted; unsupported
geometry fails explicitly, never silently loses semantic detail. Before
adding an outside asset, independently verify source permissions and source
SHA-256; the sample originals have an origin declaration in `AUTHORSHIP.md`.

See `RENDERER_COMPAT.md` for the decoder activation gate.
