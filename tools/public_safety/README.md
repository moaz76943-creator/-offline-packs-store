# Public publication security gate

Standard-library-only, offline, fail-closed scanner of **staged** Git index objects for the public pack store. It does not read the private application repository, contact a secrets service, run CI, or rewrite Git history.

From the **public** repository root, stage intended changes and run:

```sh
python3 tools/public_safety/gate.py --repo . --save-private-evidence
python3 -m unittest discover -s tools/public_safety -p 'test_*.py' -v
python3 -m compileall -q tools/public_safety
git diff --cached --check
git diff --check
```

Every publication job must run the first command **after staging the exact intended export and before any commit or upload**. Abort for every nonzero code. Exit codes are `0=PASS`, `1=FAIL` (policy violation), `2=BLOCKED` (insufficient proof, invalid environment or incomplete scan). A clean run means only that the staged change passed the rules implemented by this scanner; it is not an assurance that all historical objects are clean.

## Export rules

Only documentation, neutral text/JSON schemas and catalogs, known index files, public tooling under `tools/public_safety/`, licensed media under `images/` or `media/`, and `.pack.gz` under `packs/` are eligible. Unknown paths are denied. Media and packs **must** have their exact SHA-256, approved SPDX license and provenance recorded in `tools/public_safety/provenance.json` before staging. Each pack also requires matching `manifest.json` SHA-256 metadata. A blanket public-domain claim or manifest hash alone does not establish licensing rights. Do not invent an attribution record; supply evidence and require human review of its origin.

`provenance.json` has format:

```json
{
  "schema_version": 1,
  "exports": {
    "packs/example.pack.gz": {
      "sha256": "64 lowercase hex characters",
      "license": "CC0-1.0",
      "source": "https://source.example.invalid/original",
      "rights_holder": "Documented original creator",
      "attribution": "Required attribution string"
    }
  }
}
```

This ledger starts empty intentionally because existing sources and rights were not independently validated. Previously published files are not retrospectively certified. If historical-path triage is needed, run `python3 tools/public_safety/gate.py --repo . --history`; only historical **path metadata** is inspected, not historical secret values. If leaked credentials might have been published, revoke/rotate them, coordinate incident response and history removal **manually**. Never include tokens, private paths, raw diffs, or stack traces in PR comments.

Diagnostics use rule identifiers and hashed path handles only. Optional evidence is saved under `.git/public_safety_evidence/`, outside Git's trackable tree, with local access controls, and contains rule identifiers and fingerprints but **no sensitive values**. Do not upload that directory. Archives are decompressed with bounds; unsafe members and unknown file types are rejected. No external dependencies or paid services are used.

## Enforcement boundary

This tool is **not automatically invoked** by the existing publishing workflows or direct pushes. It becomes an actual mandatory protection only after all publication commands call it and `main` is protected with mandatory checks/reviews or equivalent rules. Changes to workflows or repository settings are intentionally **outside this PR's allowed write scope**. Until then, bypass remains possible. Secret detection is heuristic, so review and least-privilege publication remain necessary.
