"""Contributor evidence gate. No receipt is a grant of legal rights."""
import argparse
import hashlib
import json
from pathlib import Path

from legal.ledger.admission import KINDS, manual_review, text, url_ok
from tools.contribution_gate.evidence import (
    exact_source_reference, load_verified_ledger, required, verified_artifact
)

MAX_BYTES = 50 * 1024 * 1024

def validate_contribution(manifest_dict, repo_root):
    def block(message, status="REJECT"):
        return {"status": status, "reasons": [message], "publication_approved": False}
    if not isinstance(manifest_dict, dict):
        return block("Malformed contribution")
    try:
        if manifest_dict.get("synthetic") is True or manifest_dict.get("is_fixture") is True:
            raise ValueError("Synthetic fixtures cannot become production evidence")
        asset_id = required(manifest_dict.get("asset_id"), "asset_id")
        if asset_id.startswith(("test-", "fixture-")):
            raise ValueError("Fixture asset identity cannot be admitted")
        kind = manifest_dict.get("kind")
        if kind not in KINDS:
            raise ValueError("Invalid kind")
        root = Path(repo_root).resolve()
        src_index = load_verified_ledger(root)
        source = exact_source_reference(manifest_dict.get("source_ref"), src_index)
        if kind != source["kind"] or manifest_dict.get("license_id") != source["license"]["id"]:
            raise ValueError("Content kind or license contradicts canonical source")
        if manifest_dict.get("source_identity") != source["source_id"]:
            raise ValueError("Missing or contradictory source identity")
        if manifest_dict.get("origin_url") != source["origin_url"]:
            raise ValueError("Missing or contradictory source origin")
        actual_path = verified_artifact(root, manifest_dict.get("artifact_path"),
                                        manifest_dict.get("sha256"), "contribution bytes")
        full_path = (root / actual_path).resolve()
        if full_path.stat().st_size > MAX_BYTES:
            raise ValueError("Contribution exceeds size limit")
        rights = manifest_dict.get("contributor_authorization")
        if not isinstance(rights, dict):
            raise ValueError("Missing independently reviewable contributor authorization")
        right_path = verified_artifact(root, rights.get("artifact_path"), rights.get("sha256"),
                                       "contributor authorization proof")
        right_file = (root / right_path).resolve()
        if right_file.stat().st_size > 65536:
            raise ValueError("Contributor authorization evidence exceeds size bound")
        try:
            grant = json.loads(right_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError("Contributor authorization must be structured evidence") from exc
        if not isinstance(grant, dict) or grant.get("synthetic") is True:
            raise ValueError("Unstructured or synthetic authorization evidence")
        for key, expected in (
                ("source_id", source["source_id"]),
                ("source_version", source["dataset_version"]),
                ("asset_id", asset_id),
                ("artifact_sha256", manifest_dict["sha256"]),
                ("license_id", source["license"]["id"]),
                ("scope", "redistribution")):
            if grant.get(key) != expected:
                raise ValueError("Contributor authorization missing or mismatched " + key)
        if grant.get("license_id") == "CC0-1.0" and grant.get("cc0_declaration") is not True:
            raise ValueError("CC0 requires explicit declaration")
        if (not text(grant.get("rights_holder")) or
                not url_ok(grant.get("grant_url")) or
                grant.get("revoked") is not False):
            raise ValueError("Unverified holder, grant URL or revoked rights")
        review_errors = []
        if not manual_review(manifest_dict.get("review"), review_errors, "contribution"):
            raise ValueError("; ".join(review_errors))
        notice = manifest_dict.get("attribution_notice")
        if not isinstance(notice, dict):
            raise ValueError("Missing attribution notice")
        rel = verified_artifact(root, notice.get("artifact_path"),
                                notice.get("sha256"), "contributor attribution notice")
        content = (root / rel).resolve().read_text(encoding="utf-8")
        if not all(term in content for term in (source["source_id"], source["publisher"],
                                                source["origin_url"], source["license"]["id"])):
            raise ValueError("Incomplete source-specific attribution")
        if manifest_dict.get("source_verification") != "verified":
            raise ValueError("Source verification missing or revoked")
        if manifest_dict.get("permission_revoked") is not False:
            raise ValueError("Contributor permission not affirmatively current")
        if kind == "vector_art":
            rights_info = source["license"]
            for key in ("artwork_evidence_url", "artwork_evidence_path", "artwork_evidence_sha256"):
                required(rights_info.get(key), "separate artwork rights evidence")
        receipt_id = hashlib.sha256(
            (asset_id + "|" + manifest_dict["sha256"] + "|" +
             source["retrieval"]["sha256"]).encode("utf-8")).hexdigest()
        return {"status": "ACCEPT" if source.get("status") == "APPROVED_FOR_REDISTRIBUTION" else "REVIEW_REQUIRED", "reasons": [] if source.get("status") == "APPROVED_FOR_REDISTRIBUTION" else ["Source status is not approved"],
                "publication_approved": False,
                "receipt": {"receipt_id": receipt_id, "source_id": source["source_id"],
                            "source_version": source["dataset_version"],
                            "source_hash": source["retrieval"]["sha256"],
                            "artifact_sha256": manifest_dict["sha256"],
                            "evidence_only": True}}
    except ValueError as exc:
        if "REVIEW_REQUIRED" in str(exc) or "source not manually approved" in str(exc):
            return block(str(exc), "REVIEW_REQUIRED")
        return block(str(exc))
    except (KeyError, OSError, TypeError, UnicodeError) as exc:
        return block(str(exc))

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest")
    p.add_argument("--repo-root", required=True)
    a = p.parse_args(argv)
    try:
        manifest = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        p.exit(2, "BLOCKED: " + str(exc) + "\n")
    result = validate_contribution(manifest, a.repo_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "ACCEPT" else 1

if __name__ == "__main__":
    raise SystemExit(main())
