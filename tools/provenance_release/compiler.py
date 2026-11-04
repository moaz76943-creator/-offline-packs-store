#!/usr/bin/env python3
"""Verified Release Provenance Compiler.

Generates a machine-readable release provenance manifest and a human-readable attribution notice.
Excludes unverified materials from the release manifest.
"""
import argparse
import json
import logging
import sys
from pathlib import Path

# We reuse the logic from legal.ledger.admission as much as possible for validation.
from legal.ledger.admission import SCHEMA, KINDS, LICENSES, OBLIGATIONS, sha256_file, text

logger = logging.getLogger(__name__)

class ProvenanceCompiler:
    def __init__(self, root: Path, ledger_path: Path, daily_dir: Path):
        self.root = root.resolve()
        self.ledger_path = ledger_path.resolve()
        self.daily_dir = daily_dir.resolve()

    def compile(self, manifest_out: Path, notice_out: Path) -> dict:
        """
        Compile provenance and output release_provenance.json and NOTICE.txt.
        Returns a dictionary of statuses for tests.
        """
        try:
            with open(self.ledger_path, 'r', encoding='utf-8') as f:
                ledger = json.load(f)

            dailies = []
            if self.daily_dir.exists():
                for p in sorted(self.daily_dir.glob('*.json')):
                    with open(p, 'r', encoding='utf-8') as f:
                        dailies.append(json.load(f))
        except (OSError, ValueError) as exc:
            logger.error(f"Cannot read admission inputs: {exc}")
            raise

        sources_by_id = {src.get('source_id'): src for src in ledger.get('sources', []) if isinstance(src, dict)}

        # Evaluate is mostly for overall blocks, but we also want per-candidate states.
        # We'll re-implement the per-candidate check to extract exact statuses for our output.

        statuses = {'approved': [], 'blocked': [], 'review_required': [], 'invalid': []}
        provenance = []
        notices = []

        seen_cids = set()

        for daily_index, daily in enumerate(dailies):
            if not isinstance(daily, dict) or daily.get('schema_version') != SCHEMA:
                statuses['invalid'].append(f'daily[{daily_index}]')
                continue

            items = daily.get('release_candidates', [])
            if not isinstance(items, list):
                statuses['invalid'].append(f'daily[{daily_index}].release_candidates')
                continue
            for entry_index, entry in enumerate(items):
                if not isinstance(entry, dict):
                    statuses['invalid'].append(
                        f'daily[{daily_index}].release_candidates[{entry_index}]')
                    continue

                cid = entry.get('asset_id')
                if not text(cid):
                    statuses['invalid'].append(
                        f'daily[{daily_index}].release_candidates[{entry_index}]')
                    continue

                if cid in seen_cids:
                    # duplicate provenance
                    statuses['invalid'].append(cid)
                    continue
                seen_cids.add(cid)

                # Check candidate properties
                is_valid = True
                block_reason = None

                if entry.get('kind') not in KINDS:
                    is_valid = False
                    block_reason = "invalid kind"

                artifact_path = entry.get('artifact_path')
                expected_sha = entry.get('sha256')

                if not text(artifact_path) or not expected_sha:
                    is_valid = False
                    block_reason = "missing path or hash"
                else:
                    resolved_path = (self.root / artifact_path).resolve()
                    if not resolved_path.is_relative_to(self.root) or not resolved_path.is_file():
                        is_valid = False
                        block_reason = "missing artifact"
                    elif sha256_file(resolved_path) != expected_sha:
                        is_valid = False
                        block_reason = "altered artifact hash"

                refs = entry.get('source_refs')
                if not isinstance(refs, list) or not refs:
                    is_valid = False
                    block_reason = "missing source_refs"

                resolved_sources = []
                review_required = False
                blocked_license = False

                for ref in (refs or []):
                    if not isinstance(ref, dict):
                        is_valid = False
                        continue
                    sid = ref.get('source_id')
                    src = sources_by_id.get(sid)
                    if not src:
                        is_valid = False
                        block_reason = f"unknown source {sid}"
                        continue
                    resolved_sources.append(src)

                    if src.get('status') == 'REVIEW_REQUIRED':
                        review_required = True
                    elif src.get('status') != 'APPROVED_FOR_REDISTRIBUTION':
                        blocked_license = True

                    if ref.get('dataset_version') != src.get('dataset_version'):
                        is_valid = False
                        block_reason = "version mismatch"

                    if ref.get('artifact_sha256') != (src.get('retrieval') or {}).get('sha256'):
                        is_valid = False
                        block_reason = "source hash mismatch"

                out_lic = entry.get('output_license_id')
                if out_lic not in LICENSES:
                    is_valid = False
                    block_reason = "unsupported output license"

                copyleft = {s['license']['id'] for s in resolved_sources if s.get('license', {}).get('id') in OBLIGATIONS}
                if len(copyleft) > 1:
                    is_valid = False
                    block_reason = "mixed licensing conflict"

                for src in resolved_sources:
                    lid = src.get('license', {}).get('id')
                    if lid in OBLIGATIONS and out_lic != lid:
                        is_valid = False
                        block_reason = "relicensing conflict"

                entry_notices = entry.get('notices', {})
                for src in resolved_sources:
                    sid = src['source_id']
                    rel = entry_notices.get(sid)
                    if not text(rel):
                        is_valid = False
                        block_reason = "missing notice"
                        continue
                    try:
                        p = (self.root / rel).resolve()
                        if not p.is_relative_to(self.root) or not p.is_file():
                            is_valid = False
                            block_reason = "invalid notice path"
                            continue
                        content = p.read_text(encoding='utf-8')
                        terms = [sid, src.get('publisher', ''), src.get('license', {}).get('id', ''), src.get('origin_url', '')]
                        if 'author' in src:
                            terms.append(src['author'])
                        if not all(term in content for term in terms):
                            is_valid = False
                            block_reason = "incomplete notice"
                        else:
                            notices.append(f"--- Notice for {cid} from {sid} ---\n{content}\n")
                    except Exception:
                        is_valid = False
                        block_reason = "unreadable notice"

                if not is_valid:
                    statuses['invalid'].append(cid)
                    continue

                if blocked_license:
                    statuses['blocked'].append(cid)
                    continue

                if review_required:
                    statuses['review_required'].append(cid)
                    continue

                # Verified & Approved
                statuses['approved'].append(cid)
                prov = {
                    "asset_id": cid,
                    "kind": entry.get('kind'),
                    "artifact_path": artifact_path,
                    "sha256": expected_sha,
                    "output_license_id": out_lic,
                    "compiler_license_id": entry.get('compiler_license_id'),
                    "sources": []
                }
                for src in resolved_sources:
                    source_dict = {
                        "source_id": src.get('source_id'),
                        "dataset_version": src.get('dataset_version'),
                        "publisher": src.get('publisher'),
                        "license": src.get('license', {}).get('id'),
                        "alterations": src.get('alterations', [])
                    }
                    if 'author' in src:
                        source_dict['author'] = src['author']
                    prov['sources'].append(source_dict)
                provenance.append(prov)

        # Write manifest
        with open(manifest_out, 'w', encoding='utf-8') as f:
            json.dump({
                "schema_version": "1.0.0",
                "release_provenance": provenance,
                "blocked": sorted(statuses['blocked']),
                "review_required": sorted(statuses['review_required'])
            }, f, indent=2)

        # Write notice
        with open(notice_out, 'w', encoding='utf-8') as f:
            f.write("ATTRIBUTION NOTICES\n===================\n\n")
            f.write("\n".join(notices))

        return statuses

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path.cwd())
    parser.add_argument('--ledger', type=Path)
    parser.add_argument('--daily-dir', type=Path)
    parser.add_argument('--manifest-out', type=Path, required=True)
    parser.add_argument('--notice-out', type=Path, required=True)
    args = parser.parse_args(argv)

    root = args.repo_root.resolve()
    ledger_path = args.ledger or root / 'legal/ledger/sources.json'
    daily_dir = args.daily_dir or root / 'legal/ledger/daily'

    compiler = ProvenanceCompiler(root, ledger_path, daily_dir)
    statuses = compiler.compile(args.manifest_out, args.notice_out)

    print("Machine validation is not a legal opinion.", file=sys.stderr)

    if statuses.get('invalid'):
        print(f"Compilation failed due to {len(statuses['invalid'])} invalid candidates.", file=sys.stderr)
        return 1

    return 0

if __name__ == '__main__':
    sys.exit(main())
