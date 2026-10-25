# Source licensing and provenance gate v1.0.0

This is a fail-closed, offline, standard-library-only admission validator for the PUBLIC content repository. It provides a repeatable evidence gate, **not a legal opinion**.

**Baseline: NO-GO.** The current public manifest declares the blanket intellectual-property status PUBLIC_DOMAIN_ZERO_COPYRIGHT and marks 100 packs active. Neither upstream corpus license notices nor source artifact hashes are documented in this repository. The source ledger starts empty to avoid fabricating evidence or silently approving third-party material. The validator rejects the blanket claim and all active packs without source-backed daily admission candidates. This scoped PR does not remove previously public files or activate a CI workflow.

## Run locally

    python3 legal/ledger/admission.py --repo-root .
    python3 -m unittest discover -s legal/ledger -p 'test_*.py' -v
    python3 -m compileall -q legal/ledger
    git diff --check

Exit code 0 means recorded evidence passed the programmatic checks, **not that legal rights have been independently established**. Code 1 means blocked; code 2 means missing or malformed inputs. Publishing systems must call this validator explicitly before releasing new packs; it is not automatically installed as a GitHub protection rule.

## Schema and evidence capture

The versioned JSON schema is in schema.json. Record one original source artifact in sources.json per dataset, morphology corpus, example collection, font, pronunciation recording, photo or vector artwork. Required metadata: stable source_id; precise HTTPS origin and retrieval URLs; real publisher/author; version; immutable retrieval identity and date; path and SHA-256 of the actual downloaded source bytes; source-specific rights notice URL; path and SHA-256 of the original license notice snapshot; alteration history; explicit reviewer and public decision link. Generic CC/GNU terms alone are NOT evidence the particular upstream source uses that license.

Only publicly redistributable evidence snapshots may be added. Do not move private content, credentials, user records, proprietary source, or internal logs to the public repository. Sources without permissible proofs stay BLOCKED_LICENSE or REVIEW_REQUIRED. Never guess a source hash. The reviewer must explicitly set APPROVED_FOR_REDISTRIBUTION and document an independent decision; no programmatic check can do this for them.

The license of the underlying data and compiler_license_id of the software that compiled it are different rights statements. output_license_id describes the distributed output. Normalization, translation, extraction, SQLite/JSON compilation and media processing do NOT turn third-party content into CC0.

## Specific redistribution obligations

| Source terms | Conservative admission requirements |
| --- | --- |
| CC BY-SA 4.0 | Preserve author/publisher and upstream origin credit, link the license, document changes, honor ShareAlike for covered adaptations, apply no downstream restrictions. Each obligation has its own compliance flag and per-source notice. |
| GFDL 1.3-only | Include applicable license text, attribution/copyright notices, History, invariant sections, cover texts and transparent-copy checks. Each obligation is assessed separately. **Do not treat GFDL and CC BY-SA as generally interchangeable.** |
| CC0 1.0 | Demonstrate that the specific original rightsholder chose CC0. CC0 is a waiver/fallback license, not an excuse to relabel mixed external sources public domain. |
| Public domain | Require work-specific jurisdiction, legal basis, work date and documentary proof. Blanket claims are blocked. |

Any other license family (including the SIL Open Font License) must receive separate handling rather than being silently mapped to one of these four. Fonts, sound recordings, illustrations, and SVG/vector artwork have independent ownership and rights. Vector artwork needs a separate original artwork-license URL and hashed evidence. Copyleft mixtures and special historical relicensing scenarios require human legal review; the validator conservatively blocks automatic license conversion.

Official terms for further legal analysis:
- https://creativecommons.org/licenses/by-sa/4.0/legalcode.en
- https://www.gnu.org/licenses/fdl-1.3.en.html
- https://creativecommons.org/publicdomain/zero/1.0/legalcode.en

## Daily content integration

Add one dated JSON manifest per day under daily/. Each release_candidates entry must provide:

- asset_id, kind, local artifact_path with checked SHA-256;
- source_refs with original source_id, exact dataset_version and original artifact_sha256;
- output_license_id distinct from compiler_license_id;
- per-source notices indexed by source ID; each notice must identify the source, publisher, origin URL and original license;
- separate CC BY-SA or GFDL compliance declarations and GFDL license copy as applicable;
- provenance_mode of per_record with record_sources mapping lexical record IDs to source IDs, or source_set with an explicit justification when fine-grained mapping genuinely is not available;
- a separate manual review decision.

Daily manifests are cumulative. Active entries in the public manifest require an admitted candidate referencing identical asset paths and verified source evidence. Version mismatches, changed bytes, missing attribution, unsupported licenses, unresolved sources, absent reviewer and invalid source mappings all block release. The gate fetches nothing over the network and uses no paid services.
