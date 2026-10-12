"""Versioned framework, provenance, and mapping-contract registry."""
import copy
import re

from .schema import MAX_MAPPINGS, SKILLS, ValidationError, read_json


class Registry:
    def __init__(self, frameworks: dict | None = None, mappings: dict | None = None):
        self.framework_data = copy.deepcopy(frameworks if frameworks is not None else read_json("frameworks.json"))
        self.mapping_data = copy.deepcopy(mappings if mappings is not None else read_json("mappings.json"))
        self.schema = read_json("record.schema.json")
        self._verify_registry()

    def _verify_registry(self) -> None:
        data = self.framework_data
        maps = self.mapping_data
        if data.get("schema_version") != "1.0.0" or maps.get("schema_version") != "1.0.0":
            raise ValidationError("Unsupported schema version")
        frameworks = data.get("frameworks")
        sources = data.get("sources")
        if not isinstance(frameworks, list) or not isinstance(sources, list) or len(frameworks) > 250 or len(sources) > 2000:
            raise ValidationError("Invalid registry size")
        self.sources = {}
        for source in sources:
            if not isinstance(source, dict) or set(source) - {"source_id", "publisher", "version", "url", "scope", "sha256"}:
                raise ValidationError("Malformed source")
            if not all(isinstance(source.get(k), str) and source[k].strip() for k in ("source_id", "publisher", "version", "url", "scope")):
                raise ValidationError("Incomplete source")
            if not source["url"].startswith("https://") or source["scope"] not in {"framework", "mapping", "local_taxonomy", "content_classification", "frequency"}:
                raise ValidationError("Invalid source origin or scope")
            if "sha256" in source and not re.fullmatch(r"[0-9a-f]{64}", source["sha256"]):
                raise ValidationError("Invalid source SHA-256")
            if source["source_id"] in self.sources:
                raise ValidationError("Duplicate source identifier")
            self.sources[source["source_id"]] = source
        self.frameworks = {}
        for framework in frameworks:
            if not isinstance(framework, dict) or set(framework) != {"proficiency_framework_id", "version", "kind", "language_scope", "levels", "assessed_skills", "source_id"}:
                raise ValidationError("Malformed framework")
            fid = framework["proficiency_framework_id"]
            if not isinstance(fid, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", fid) or fid in self.frameworks:
                raise ValidationError("Invalid/duplicate framework ID")
            if not isinstance(framework["version"], str) or not framework["version"]:
                raise ValidationError("Framework version is required")
            levels = framework["levels"]
            if not isinstance(levels, list) or not levels or len(levels) > 40 or any(not isinstance(k, str) or not k for k in levels) or len(levels) != len(set(levels)):
                raise ValidationError("Invalid framework levels")
            if not isinstance(framework["assessed_skills"], list) or any(s not in SKILLS for s in framework["assessed_skills"]):
                raise ValidationError("Unsupported skill")
            source = self.sources.get(framework["source_id"])
            if source is None or source["scope"] not in {"framework", "local_taxonomy"}:
                raise ValidationError("Framework source missing")
            self.frameworks[fid] = framework
        if self.frameworks.get("CEFR", {}).get("levels") != ["A1", "A2", "B1", "B2", "C1", "C2"]:
            raise ValidationError("CEFR six-level identity must remain stable")
        published = maps.get("published_reference_mappings")
        estimates = maps.get("estimated_mappings")
        if not isinstance(published, list) or not isinstance(estimates, list) or len(published) + len(estimates) > MAX_MAPPINGS:
            raise ValidationError("Invalid mapping collection")
        seen = {}
        for bucket, records in (("published", published), ("estimated", estimates)):
            for row in records:
                required = {"from_framework", "from_level", "to_framework", "to_level", "minimum_score", "maximum_score", "source_id"}
                if not isinstance(row, dict) or set(row) != required:
                    raise ValidationError("Malformed mapping")
                for prefix in ("from", "to"):
                    f, lev = row[prefix + "_framework"], row[prefix + "_level"]
                    if f not in self.frameworks or lev not in self.frameworks[f]["levels"]:
                        raise ValidationError("Mapping references unknown level")
                source = self.sources.get(row["source_id"])
                if not source or source["scope"] != "mapping":
                    raise ValidationError("Unattested mapping source")
                low, high = row["minimum_score"], row["maximum_score"]
                if type(low) is not int or type(high) is not int or not 0 <= low <= high <= 1000:
                    raise ValidationError("Invalid score range")
                key = (bucket, row["from_framework"], row["from_level"], row["to_framework"])
                for l, h in seen.get(key, []):
                    if low <= h and l <= high:
                        raise ValidationError("Conflicting overlapping mapping ranges")
                seen.setdefault(key, []).append((low, high))
        self.published = published
        self.estimates = estimates
