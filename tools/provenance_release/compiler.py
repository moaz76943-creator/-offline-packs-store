#!/usr/bin/env python3
"""Verified Release Provenance Compiler.
Builds an executable provenance compiler for publicly redistributable language data.
"""

import argparse
import json
import sys
from pathlib import Path

# Fix module import by adding repo root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from legal.ledger.admission import evaluate


def compile_release(repo_root: Path, output_manifest: Path, output_notice: Path):
    """
    Compiles release provenance by validating sources and candidates.
    """
    root = repo_root.resolve()
    ledger_path = root / 'legal/ledger/sources.json'
    manifest_path = root / 'manifest.json'
    daily_dir = root / 'legal/ledger/daily'

    if not ledger_path.exists():
        raise FileNotFoundError(f"Missing ledger: {ledger_path}")
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest: {manifest_path}")

    try:
        ledger = json.loads(ledger_path.read_text(encoding='utf-8'))
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        dailies = []
        if daily_dir.exists():
            for p in sorted(daily_dir.glob('*.json')):
                dailies.append(json.loads(p.read_text(encoding='utf-8')))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read admission inputs: {exc.__class__.__name__}")

    try:
        errors = evaluate(ledger, manifest, dailies, root)
        if errors:
            raise ValueError("Compilation rejected due to legal validation errors:\n" + "\n".join(errors))
    except Exception as e:
        raise ValueError(f"Compilation rejected: {e}")

    sources_map = {s['source_id']: s for s in ledger.get('sources', [])}
    admitted_assets = []
    notices = []

    for daily in dailies:
        for candidate in daily.get('release_candidates', []):
            asset_id = candidate.get('asset_id')
            artifact_path = candidate.get('artifact_path')
            sha256 = candidate.get('sha256')

            # Record resolved sources for provenance and notice
            provenance = []
            asset_notices = []
            for ref in candidate.get('source_refs', []):
                sid = ref.get('source_id')
                src = sources_map.get(sid)
                if not src:
                    continue

                # Exclude unverified materials (this is partly handled by admission, but we double-check)
                if src.get('status') != 'APPROVED_FOR_REDISTRIBUTION':
                    continue

                provenance.append({
                    "source_id": sid,
                    "publisher": src.get('publisher'),
                    "origin_url": src.get('origin_url'),
                    "dataset_version": src.get('dataset_version'),
                    "license": src.get('license', {}).get('id')
                })

                asset_notices.append(f"Source: {sid}\nPublisher: {src.get('publisher')}\n"
                                     f"Origin URL: {src.get('origin_url')}\n"
                                     f"License: {src.get('license', {}).get('id')}")

            if provenance:
                admitted_assets.append({
                    "asset_id": asset_id,
                    "artifact_path": artifact_path,
                    "sha256": sha256,
                    "output_license": candidate.get('output_license_id'),
                    "provenance": provenance
                })

                notices.append(f"Asset: {asset_id} ({artifact_path})")
                notices.append("Output License: " + str(candidate.get('output_license_id')))
                notices.append("Sources:")
                for n in asset_notices:
                    notices.append("  " + n.replace('\n', '\n  '))
                notices.append("-" * 40)

    # Note: explicit blocked/review_required statuses are preserved by not stripping them from sources.
    # We output a clean release manifest containing only verifiable provenance.
    release_manifest = {
        "schema_version": "1.0.0",
        "assets": admitted_assets,
        "unverified_statuses": [s for s in ledger.get('sources', []) if s.get('status') in ('BLOCKED_LICENSE', 'REVIEW_REQUIRED')]
    }

    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_notice.parent.mkdir(parents=True, exist_ok=True)

    with output_manifest.open('w', encoding='utf-8') as f:
        json.dump(release_manifest, f, indent=2, sort_keys=True)

    with output_notice.open('w', encoding='utf-8') as f:
        f.write("\n".join(notices) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path.cwd())
    parser.add_argument('--output-manifest', type=Path, default=Path('release_provenance.json'))
    parser.add_argument('--output-notice', type=Path, default=Path('NOTICE.txt'))
    args = parser.parse_args(argv)

    try:
        compile_release(args.repo_root, args.output_manifest, args.output_notice)
    except Exception as e:
        print(f"Compilation failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
