import re
from typing import Dict, Any, List
from .schema import VisualAssetMetadata

CONTROL_CHAR_RE = re.compile(r'[\x00-\x1F\x7F]')

class AccessibilityValidator:
    def validate_asset(self, asset: VisualAssetMetadata) -> Dict[str, Any]:
        errors = []
        warnings = []
        status = "accepted"

        concept_id = asset.get("concept_id")
        if not concept_id:
            errors.append("Missing semantic concept ID")

        self._validate_labels(asset, concept_id, errors, warnings)

        if not asset.get("fallback_label"):
            errors.append("Missing fallback label")

        self._validate_contrast(asset, errors)
        self._validate_vector_bounds(asset, errors)
        self._validate_provenance(asset, errors)

        if "device_shaping_evidence" not in asset or not asset["device_shaping_evidence"]:
            warnings.append("Missing device shaping evidence")

        if errors:
            status = "rejected"
        elif any(w == "REVIEW_REQUIRED" for w in warnings):
            status = "review_required"

        return {
            "status": status,
            "errors": errors,
            "warnings": warnings
        }

    def _validate_labels(self, asset: VisualAssetMetadata, concept_id: str, errors: List[str], warnings: List[str]):
        labels = asset.get("labels", [])
        if not labels:
            errors.append("Missing or empty alt text")
            return

        for label in labels:
            if not label.get("language"):
                errors.append("Missing language metadata")

            if not label.get("script"):
                errors.append("Missing script metadata")

            text = label.get("text")
            if not text:
                errors.append("Missing or empty alt text")
            elif CONTROL_CHAR_RE.search(text):
                errors.append("Alt text contains control characters")

            related_concept = label.get("related_concept_id")
            if related_concept and concept_id and related_concept != concept_id:
                errors.append("Mismatched concept ID")

            direction = label.get("direction")
            if direction not in ("ltr", "rtl"):
                errors.append("Malformed RTL/LTR direction metadata")

            if not label.get("verified", False):
                warnings.append("REVIEW_REQUIRED")

    def _validate_contrast(self, asset: VisualAssetMetadata, errors: List[str]):
        contrast = asset.get("contrast")
        if not contrast or not isinstance(contrast, dict) or "supported" not in contrast:
            errors.append("Missing or structurally invalid contrast metadata")

    def _validate_vector_bounds(self, asset: VisualAssetMetadata, errors: List[str]):
        vector = asset.get("vector")
        if not vector or not isinstance(vector, dict):
            errors.append("Missing or structurally invalid vector metadata")
            return

        bounds = vector.get("bounds")
        if not bounds or not isinstance(bounds, dict) or "max_x" not in bounds or "max_y" not in bounds:
            errors.append("Vector bounds missing or invalid")

        complexity = vector.get("complexity")
        if complexity is None:
            errors.append("Vector complexity missing")

        path_count = vector.get("path_count")
        if path_count is not None and path_count > 50:
            errors.append("Safe complexity limit exceeded")

    def _validate_provenance(self, asset: VisualAssetMetadata, errors: List[str]):
        if not asset.get("version"):
            errors.append("Missing version identity")
        if not asset.get("hash"):
            errors.append("Missing hash identity")
        if not asset.get("provenance"):
            errors.append("Missing provenance identity")
