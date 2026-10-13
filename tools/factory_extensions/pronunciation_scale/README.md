# Evidence-gated pronunciation and offline audio inventory (v1.0.0)

**Status:** software and synthetic QA fixtures only. candidates.json is empty. The Route-05 ledger legal/ledger/sources.json had zero admitted sources at 2026-10-13. No language has demonstrated packaged audio from this extension. Candidate rights research must not be treated as licensing approval.

This is a read-only adapter over canonical 100-language identities, existing lexical lexeme/sense IDs, and the Route-05 source ledger. It does not change Jules PR #97's tools/pronunciation_metadata/** or PR #99's tools/audio_pronunciation/**. After those PRs merge, reconcile their versioned contracts explicitly. A candidate publication_approved flag alone does not confer rights. There are no downloads, private files, generation, or corpus mutations.

Each versioned record has pronunciation_id, lexeme_id, optional sense_id, language_id, BCP-47 language_tag, registered script, variant_id, source-attested reading (notation, value, optional syllables, stress, tones) and evidence (source_id, publisher, dataset_version, record_locator, license_id). Readings remain independent of spelling and are never synthesized from German or another language's phonology.

Each audio asset has asset_id, kind, path, sha256, license_id, exact licensed rights_url, rights_evidence_path and rights_evidence_sha256, and speaker_id for human recordings. Generated assets additionally require a generation object with licensed engine_id, voice_id, commercial_redistribution_approved, terms_url, proof_path and proof_sha256. Both require the unique reviewed Route-05 source, source artifact and source license snapshots with matching hashes. Noncommercial, unclear, mixed, forged, unreviewed ShareAlike/GFDL and missing-per-record-license cases fail closed. No original asset is removed, quarantined or rewritten.

A device_tts candidate is **not** a downloadable audio file and is excluded. An OS voice is available offline only after a runtime check confirms the actual installed voice; locale compatibility is insufficient. The safe codec profile currently supports fully decoded PCM WAV only (mono/stereo, 8–96 kHz, up to 15 seconds and 2 MiB). MP3, Ogg and Opus require a reviewed bounded decoder integration before inclusion; their existence is not equivalent to successful decoding.

Deterministic TAR packaging indexes accepted WAV content by SHA-256, deduplicates identical bytes without altering originals, and uses zero timestamps. Do not use synthetic tests as real linguistic or recording evidence.

Run from repository root:

    python3 -m unittest discover -s tests/factory_extensions/pronunciation_scale -p 'test_*.py' -v
    python3 -m tools.factory_extensions.pronunciation_scale.factory --output-dir /tmp/pronunciation-scale-checkpoint

coverage.json reports attested pronunciation variants, unique decoded audio files and asset count for each registered language, rather than inferred 100-language coverage. admission.json contains admitted evidence and explicit rejection reasons. audio.tar exists only when approved audio is present.

Runs refuse batches over 500 records. Shard upstream and upload completed read-only checkpoints as GitHub Actions artifacts for durable replay; an interrupted in-flight batch must be retried, never assumed saved. The workflow is standard public Actions (read-only; 10-minute timeout; 7-day retention). The empty-ledger condition means no source ingestion job is eligible today.

Compatibility adapters in adapters.py read PR #97's registry_version=1.0.0 records into independent pronunciation candidates without trusting its offline_voice_status or inventing audio. Missing per-reading locators fail closed. PR #99's assets can be inspected, but remain quarantined until independent per-speaker, per-recording rights are supplied. No PR-owned file is modified.

coverage_baseline.json is a pinned **actual empty-ledger snapshot** of all 100 registered language IDs based on main SHA 254e8edd85a2d4a37c13e1834ef2d9f77ce7e605; it is not an evergreen coverage promise. The latest CLI report supersedes the snapshot. Physical audio packaging is further limited to 64 MiB per batch, in addition to the per-file and 500-record limits.
