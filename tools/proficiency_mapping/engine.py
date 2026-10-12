"""Validated proficiency records, bounded enrichment, and explicit comparison API."""
import copy

from .registry import Registry
from .schema import MAX_RECORDS, SKILLS, ValidationError, _check, read_json


class ProficiencyCatalog(Registry):
    def validate_record(self, record: dict) -> dict:
        _check(record, self.schema, self.schema["$defs"])
        status = record["classification_status"]
        fid, level = record["proficiency_framework_id"], record["proficiency_level_id"]
        if status in {"unknown", "unassessed"}:
            if fid is not None or level is not None or record["evidence"]:
                raise ValidationError("Unassessed/unknown records cannot claim a level")
            if any(v != "unknown" for v in record["complexity"].values()):
                raise ValidationError("Unassessed content cannot claim rated difficulty")
            if any(v["status"] not in {"unknown", "not_assessed"} for v in record["skills"].values()):
                raise ValidationError("Unassessed record cannot claim skills")
        else:
            if fid not in self.frameworks or level not in self.frameworks[fid]["levels"] or not record["evidence"]:
                raise ValidationError("Classification requires a valid level and evidence")
            scope = self.frameworks[fid]["language_scope"]
            if scope != "multilingual" and record["language"].split("-")[0] != scope:
                raise ValidationError("Language is out of framework scope")
        for skill, mode in SKILLS.items():
            if record["skills"][skill]["mode"] != mode:
                raise ValidationError("Receptive/productive skill direction mismatch")
        if record["record_id"] in record["prerequisites"]:
            raise ValidationError("Self-dependency")
        for evidence in record["evidence"]:
            source = self._evidence_source(evidence)
            if status == "estimated":
                if evidence["method"] != "descriptor_guided_review" or source["scope"] != "framework":
                    raise ValidationError("Estimates need framework-based manual review")
            elif status == "source_attested":
                if evidence["method"] != "published_content_assignment" or source["scope"] != "content_classification" or "sha256" not in source:
                    raise ValidationError("Published classification requires curated artifact SHA-256")
            else:
                raise ValidationError("Unexpected evidence")
        for evidence in record.get("frequency_evidence", []):
            source = self._evidence_source(evidence)
            if source["scope"] != "frequency":
                raise ValidationError("Frequency corpus must have its own source")
        return record

    def _evidence_source(self, entry: dict) -> dict:
        source = self.sources.get(entry["source_id"])
        if source is None or entry["source_version"] != source["version"] or entry["source_url"] != source["url"]:
            raise ValidationError("Evidence identity or version does not match registered source")
        return source

    def validate_records(self, records: list[dict]) -> None:
        if not isinstance(records, list) or len(records) > MAX_RECORDS:
            raise ValidationError("Invalid number of records")
        ids = set()
        for record in records:
            self.validate_record(record)
            if record["record_id"] in ids:
                raise ValidationError("Duplicate record ID")
            ids.add(record["record_id"])
        graph = {r["record_id"]: r["prerequisites"] for r in records}
        if any(p not in graph for deps in graph.values() for p in deps):
            raise ValidationError("Unresolved progression prerequisite")
        state = {}
        for root in sorted(graph):
            if state.get(root) == 2:
                continue
            stack = [(root, False)]
            while stack:
                node, finishing = stack.pop()
                if finishing:
                    state[node] = 2
                    continue
                if state.get(node) == 2:
                    continue
                if state.get(node) == 1:
                    raise ValidationError("Cyclic progression prerequisite")
                state[node] = 1
                stack.append((node, True))
                for parent in reversed(graph[node]):
                    if state.get(parent) == 1:
                        raise ValidationError("Cyclic progression prerequisite")
                    if state.get(parent) != 2:
                        stack.append((parent, False))

    def enrich(self, existing: list[dict], incoming: list[dict]) -> list[dict]:
        self.validate_records(existing)
        if not isinstance(incoming, list) or len(incoming) > MAX_RECORDS:
            raise ValidationError("Invalid enrichment batch")
        for record in incoming:
            self.validate_record(record)
        if len({r["record_id"] for r in incoming}) != len(incoming):
            raise ValidationError("Duplicate incoming record ID")
        merged = {r["record_id"]: copy.deepcopy(r) for r in existing}
        for record in incoming:
            rid = record["record_id"]
            if rid in merged and merged[rid] != record:
                raise ValidationError("Conflicting enrichment: explicit revision required")
            merged[rid] = copy.deepcopy(record)
        result = [merged[k] for k in sorted(merged)]
        self.validate_records(result)
        return result

    def map_level(self, from_framework: str, from_level: str, to_framework: str,
                  *, passed: bool | None = None, total_score: int | None = None,
                  skill: str | None = None, allow_estimated: bool = False) -> dict:
        if from_framework not in self.frameworks or from_level not in self.frameworks[from_framework]["levels"] or to_framework not in self.frameworks:
            raise ValidationError("Unknown framework or level")
        if skill is not None and skill not in SKILLS:
            raise ValidationError("Unknown skill")
        if type(total_score) is not int and total_score is not None:
            raise ValidationError("Score must be an integer")
        if passed is not None and type(passed) is not bool:
            raise ValidationError("Pass flag must be boolean")
        unknown = {"status": "unknown", "proficiency_framework_id": to_framework,
                   "proficiency_level_id": None, "reason": "No verified and applicable comparison"}
        if from_framework == to_framework:
            return {"status": "same_framework", "proficiency_framework_id": to_framework,
                    "proficiency_level_id": from_level, "reason": "Identity only; not a competence certification"}
        if from_framework == "JLPT":
            if passed is not True or total_score is None or skill not in {"reading", "listening"}:
                return unknown
        choices = [(r, "published_reference") for r in self.published]
        if allow_estimated:
            choices.extend((r, "estimated_not_official") for r in self.estimates)
        matches = [(r, kind) for r, kind in choices
                   if r["from_framework"] == from_framework and r["from_level"] == from_level
                   and r["to_framework"] == to_framework
                   and total_score is not None and r["minimum_score"] <= total_score <= r["maximum_score"]]
        if len(matches) != 1:
            return unknown
        row, kind = matches[0]
        source = self.sources[row["source_id"]]
        return {"status": kind, "proficiency_framework_id": to_framework,
                "proficiency_level_id": row["to_level"], "source_id": row["source_id"],
                "source_version": source["version"], "source_url": source["url"],
                "scope": "JLPT receptive competence only" if from_framework == "JLPT" else "bounded comparison",
                "certifies_full_proficiency": False}


def validate_curricula(data: dict, catalog: ProficiencyCatalog) -> None:
    if set(data) != {"schema_version", "tracks"} or data["schema_version"] != "1.0.0" or not isinstance(data["tracks"], list) or len(data["tracks"]) > 100:
        raise ValidationError("Invalid curricula container")
    for track in data["tracks"]:
        if set(track) != {"language", "proficiency_framework_id", "stages", "script_codes"}:
            raise ValidationError("Invalid curriculum track")
        framework = catalog.frameworks.get(track["proficiency_framework_id"])
        if framework is None or not isinstance(track["stages"], list) or len(track["stages"]) > 40:
            raise ValidationError("Unknown curriculum framework")
        seen = set()
        for stage in track["stages"]:
            if set(stage) != {"proficiency_level_id", "prerequisites", "topic_domains", "content_record_ids", "status"}:
                raise ValidationError("Invalid stage shape")
            level = stage["proficiency_level_id"]
            if level not in framework["levels"] or level in seen or stage["status"] != "planned_no_content" or stage["content_record_ids"] != []:
                raise ValidationError("Cannot claim content or nonexistent level")
            if any(p not in seen for p in stage["prerequisites"]):
                raise ValidationError("Curriculum prerequisite not yet reached")
            if not isinstance(stage["topic_domains"], list):
                raise ValidationError("Invalid topics")
            seen.add(level)
