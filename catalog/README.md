# Canonical 100-language registry (v1.0.0)

This contains **public linguistic metadata**, not vocabulary/translation packs. It preserves all 100 stable public IDs from ../manifest.json at reviewed commit bb15e9f02b216bbcb62a254d4a5bd695d405e9d5. It does not import private catalogs or application files.

## Files

- language_registry.v1.json: 100 canonical product identities; native and English/Arabic names; unchanged published family labels; scripts, regions, related dialects; provisional morphology; applicable proficiency frameworks.
- language_registry.schema.json: JSON Schema 2020-12 with shape, cardinality, and controlled-vocabulary checks.
- content_readiness.v1.json: separate per-ID content states, all unverified. Manifest is_active and pack filenames are not content-validation evidence.
- migration_evidence.v1.json: explicit product selection decisions and unverified reported nine-code mismatch. No private files or code lists are copied.
- validate_registry.py: standard-library-only invariant checker comparing public manifest, IDs, family labels, aliases, variants, directions, and readiness.
- test_registry.py: regression and public-manifest integration tests.

## Validate offline (no installs, CI, or paid tools)

    python3 catalog/validate_registry.py
    python3 -m unittest discover -s catalog -p 'test_*.py' -v
    python3 -m compileall -q catalog
    git diff --check

The validator supports an intentional BCP-47 structural subset, not a live IANA subtag registry. Scripts have ISO 15924 identifiers and their **own** Unicode text direction. For instance, ku-Latn is LTR while ku-Arab is RTL. Traditional Mongolian (Mong) is primarily top-to-bottom with left-to-right columns; Han and Japanese scripts also record optional vertical writing modes. Hebr is RTL even though Hebrew (he) is not currently among the published 100 selected product IDs. Do not delete a supported product identity to add it without explicit migration approval.

zh-Hans and zh-Hant are script variants of the single existing zh product ID. The ku-Latn and ku-Arab variants do not mean that Central and Northern Kurdish are the same language. The provisional fallbacks nb → no and fil → tl are marked **lossy**, not guaranteed linguistic equivalence or proof that an appropriate content pack exists.

Each morphology features array lists relevant characteristics, and all records are provisional. **Absence from the list is not a negative typological claim.** The profiles do not encode pairwise transformations.

The scales CEFR, JLPT, HSK, TOPIK are separate; no automatic score/level equivalence is asserted. An empty frameworks list is allowed if none is evaluated as applicable. The not_mapped proficiency state and unverified content state are independent.

## Incremental updates

1. Re-read the current public main HEAD and manifest. Preserve existing stable IDs and native names; require an explicit versioned migration for changes to published language selection.
2. Edit only records supported by public evidence, retain unresolved dialect/script and alias decisions, and never interpret metadata as available content.
3. Add focused regression tests; run the offline commands above before review. Registry storage remains O(N), not 9,900 language pairs.
4. Record further publicly approved mapping evidence in migration_evidence.v1.json without copying private catalog files.

Public conventions: IETF BCP 47 (RFC 5646 and RFC 4646), Unicode CLDR script data and ISO 15924 script identifiers.
