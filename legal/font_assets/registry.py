"""Offline font evidence preflight. EVIDENCE_PASS is not legal clearance or pack admission."""
import hashlib
from dataclasses import dataclass
import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from legal.ledger.admission import HASH, artifact, manual_review, text, url_ok

# Font-specific candidate license IDs: the canonical ledger currently does NOT admit
# OFL/UFL/Apache/MIT font sources. Never present this result as ledger approval.
FONT_LICENSES = frozenset({"OFL-1.1", "UFL-1.0", "Apache-2.0", "MIT", "CC0-1.0", "PUBLIC-DOMAIN"})

@dataclass
class FontAsset:
    id: str
    family: str
    source: str
    version: str
    author: str
    license_id: str
    scripts: list
    embedded: bool = False
    sha256: Optional[str] = None
    license_text_included: bool = False
    asset_path: Optional[str] = None
    origin_url: Optional[str] = None
    license_evidence_url: Optional[str] = None
    license_evidence_path: Optional[str] = None
    license_evidence_sha256: Optional[str] = None
    distribution_notice_path: Optional[str] = None
    distribution_notice_sha256: Optional[str] = None
    review: Optional[dict] = None
    review_evidence_path: Optional[str] = None
    review_evidence_sha256: Optional[str] = None
    public_domain_proof: Optional[dict] = None

class FontRightsRegistry:
    # No vendor or font family receives a blanket license inference.
    def validate_asset(self, asset: FontAsset, expected_hash=None, *, repo_root=None):
        issues = []
        if not isinstance(asset, FontAsset):
            return {"status": "REJECT", "issues": ["Invalid asset record"], "publication_approved": False}
        if not all(text(x) for x in (asset.id, asset.family, asset.source, asset.version, asset.author)):
            issues.append("Missing font identity, author, source or version")
        elif asset.source.casefold() == "unknown":
            issues.append("Unknown sources are rejected")
        if text(asset.family) and "," in asset.family:
            issues.append("Mixed font families are not supported")
        if not isinstance(asset.scripts, list) or not asset.scripts or not all(text(x) for x in asset.scripts):
            issues.append("Missing script identities")
        if not isinstance(asset.license_id, str) or asset.license_id not in FONT_LICENSES:
            issues.append("Unknown, unsupported or unverified rights")
        if not url_ok(asset.origin_url) or not url_ok(asset.license_evidence_url):
            issues.append("Original source and source-specific HTTPS license URL required")
        if isinstance(asset.license_evidence_url, str) and any(s in asset.license_evidence_url for s in (
                "opensource.org/licenses/", "scripts.sil.org/OFL", "creativecommons.org/licenses/",
                "creativecommons.org/publicdomain/zero/")):
            issues.append("Generic license terms are not source-specific permission evidence")
        if repo_root is None:
            issues.append("Repository root required to verify actual bytes")
        else:
            artifact(repo_root, asset.license_evidence_path, asset.license_evidence_sha256,
                     issues, "font license source evidence")
            artifact(repo_root, asset.review_evidence_path, asset.review_evidence_sha256,
                     issues, "independent rights review snapshot")
        manual_review(asset.review, issues, "font review")
        if asset.license_id == "PUBLIC-DOMAIN":
            pd = asset.public_domain_proof
            if not isinstance(pd, dict) or not all(text(pd.get(k)) for k in (
                    "jurisdiction", "legal_basis", "work_date")):
                issues.append("Documented public-domain basis, jurisdiction and date required")
        if asset.embedded:
            if not isinstance(asset.sha256, str) or not HASH.fullmatch(asset.sha256):
                issues.append("Embedded file requires valid SHA-256")
            if not text(asset.asset_path):
                issues.append("Embedded font bytes path required")
            if repo_root is not None:
                artifact(repo_root, asset.asset_path, asset.sha256, issues, "embedded font bytes")
            # Caller-supplied expected_hash is an additional comparison, never proof.
            if expected_hash is not None and expected_hash != asset.sha256:
                issues.append("Expected hash differs from font record")
            if not asset.license_text_included:
                issues.append("Embedded redistribution notice not declared")
            if repo_root is not None:
                if artifact(repo_root, asset.distribution_notice_path,
                            asset.distribution_notice_sha256, issues,
                            "distributed license text"):
                    path = (Path(repo_root).resolve() / asset.distribution_notice_path).resolve()
                    content = path.read_text(encoding="utf-8", errors="replace")
                    markers = {"OFL-1.1": "SIL OPEN FONT LICENSE",
                               "Apache-2.0": "Apache License", "MIT": "MIT License",
                               "UFL-1.0": "Ubuntu Font Licence"}
                    marker = markers.get(asset.license_id) if isinstance(asset.license_id, str) else None
                    if marker and marker.casefold() not in content.casefold():
                        issues.append("Distributed notice does not contain claimed license")
        else:
            # Registry metadata does not attest redistribution of uninspected bytes.
            return {"status": "REVIEW_REQUIRED", "issues": issues + [
                "Metadata-only font has no verified embedded bytes"], "publication_approved": False}
        return {"status": "REJECT" if issues else "EVIDENCE_PASS",
                "issues": issues, "publication_approved": False}

    def build_script_mapping(self, assets, *, repo_root=None):
        mapping = {}
        for asset in assets:
            result = self.validate_asset(asset, repo_root=repo_root)
            if result["status"] != "EVIDENCE_PASS":
                raise ValueError(f"Unverifiable font asset: {asset.id} - {result['issues']}")
            for script in asset.scripts:
                mapping.setdefault(script, []).append(asset.id)
        return mapping


def main(argv=None):
    parser = argparse.ArgumentParser(description="Font Licensing Registry Validator")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("manifest", type=Path, help="JSON list of font assets")
    args = parser.parse_args(argv)

    try:
        raw_assets = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(raw_assets, list):
            raise ValueError("Manifest must contain a JSON list of assets")

        assets = [FontAsset(**item) for item in raw_assets]
    except (OSError, ValueError, TypeError) as exc:
        print(f"ERROR reading manifest: {exc}", file=sys.stderr)
        return 1

    registry = FontRightsRegistry()
    try:
        mapping = registry.build_script_mapping(assets, repo_root=args.repo_root)
        print(json.dumps(mapping, indent=2))
        return 0
    except ValueError as exc:
        print(f"BLOCK: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
