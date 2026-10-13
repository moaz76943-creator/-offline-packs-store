import hashlib
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

@dataclass
class FontAsset:
    id: str
    family: str
    source: str
    version: str
    author: str
    license_id: str
    scripts: List[str]
    embedded: bool = False
    sha256: Optional[str] = None
    license_text_included: bool = False

class FontRightsRegistry:
    APPROVED_LICENSES = {"OFL-1.1", "UFL-1.0", "Apache-2.0", "MIT", "CC0-1.0", "PUBLIC-DOMAIN"}
    KNOWN_SOURCES = {"google_fonts", "sil", "mozilla", "canonical_ubuntu", "adobe"}

    def validate_asset(self, asset: FontAsset, expected_hash: Optional[str] = None) -> Dict[str, Any]:
        issues = []
        status = "accepted"

        # Check required fields
        if not asset.id or not asset.family or not asset.source or not asset.version or not asset.author or not asset.license_id or not asset.scripts:
            issues.append("Missing required fields")
            status = "rejected"
            return {"status": status, "issues": issues}

        if asset.source not in self.KNOWN_SOURCES:
            issues.append(f"Unknown source: {asset.source}")
            status = "rejected"

        # Mixed families
        if len(set(asset.family.split(","))) > 1:
            issues.append("Mixed families are not allowed")
            status = "rejected"

        if asset.license_id not in self.APPROVED_LICENSES:
            issues.append(f"Unrecognized or blocked license: {asset.license_id}")
            if status == "accepted":
                status = "reviewRequired"

        # Noto-like font specific rule
        if "Noto" in asset.family and asset.license_id != "OFL-1.1":
            issues.append("Noto-like fonts must be OFL-1.1 licensed")
            status = "rejected"

        if asset.embedded:
            if not asset.sha256:
                issues.append("Embedded assets must have a SHA-256 hash")
                status = "rejected"
            elif expected_hash and asset.sha256 != expected_hash:
                issues.append("Changed font hashes: actual hash does not match expected hash")
                status = "rejected"

            if asset.license_id in {"OFL-1.1", "Apache-2.0", "MIT", "UFL-1.0"} and not asset.license_text_included:
                issues.append("Missing license notice for embedded asset")
                status = "rejected"

        if issues and status == "accepted":
             status = "reviewRequired"

        return {"status": status, "issues": issues}
