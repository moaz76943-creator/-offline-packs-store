# DEUTSCH-IMPROVE-09 — source-specific rights evidence preflight

**Not a second admission gate, legal approval or pack release system.** This standard-library offline reader consumes the existing `legal/ledger/sources.json` shape; it does not edit the ledger, mutate license statuses, fetch sources, invoke workers or release packs. The existing `legal/ledger/admission.py` remains the definitive executable release admission gate after independent review.

## Run

```sh
python3 tools/licensing_audit/audit.py --repo-root . \
  --json-report /tmp/deutsch-rights-audit.json \
  --markdown-report /tmp/deutsch-rights-audit.md
python3 -m unittest discover -s tests/licensing_audit -p 'test_*.py' -v
```

Non-APPROVED source preflight returns exit status 1. For the current empty registry the expected status is `UNKNOWN`, `release_ready=false`, not `PASS`. The only `APPROVED` outcome requires local original source bytes, source-specific notice bytes, exact matching hashes, an approved canonical record, an identified reviewer and a decision URL; even this cannot grant a production release. Unit tests create artificial temporary bytes only (`TEST_ONLY`). These are **not** licensed production content or authentic snapshots.

### Boundaries and limitations

- This tool never makes network requests. Evidence URL checks enforce safe HTTPS shape; they do **not** authenticate remote authors, transport, or publisher signatures. SHA256 verifies **local retained bytes only**; a matching hash must not be interpreted as evidence that a source publisher authorized that content.
- The parser detects common CC BY-SA, GFDL and CC0 markers in the **hashed source-specific notice**, including apparent NC/ND restrictions or metadata disagreement. It cannot fully parse all natural-language license declarations; ambiguity becomes `REVIEW_REQUIRED` rather than guessed CC0. Dual-license notices require explicit legal route selection.
- Source artifacts are hashed in chunks (max 2 GiB); notices are capped at 512 KiB. Evidence paths may not escape the root or pass through symlinks. Generic Creative Commons license legalcode pages cannot serve as source-specific rights proof.
- Images, audio, artwork and fonts have independent third-party rights and are `REVIEW_REQUIRED` for per-item evidence. A dictionary text license does not license media automatically.
- No producer should make any `PACK_READY` decision from this report. Existing admission gate, output attribution and ShareAlike fulfillment, content provenance, real pipeline QA and human decision must pass separately.
