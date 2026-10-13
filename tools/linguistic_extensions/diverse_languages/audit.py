"""Evidence-gated, bounded review of typologically diverse language candidates.

No language substitution, inferred paradigms, network downloads, or corpus publishing.
Only standard-library dependencies. Independent of pending PR #88/#93/#94.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent

# Independent research questions, NOT validated morphology assertions.
RESEARCH_FOCUS = {
    "sw": ("noun_class_inventory", "class_agreement", "verb_extensions"),
    "zu": ("noun_class_inventory", "concord", "verb_extensions"),
    "xh": ("noun_class_inventory", "concord", "click_orthography"),
    "rw": ("noun_class_inventory", "agreement", "verbal_morphology"),
    "sn": ("noun_class_inventory", "agreement", "orthographic_variants"),
    "yo": ("tone_orthography", "regional_variants", "word_formation"),
    "ig": ("tone_orthography", "dialect_specific_spelling", "verb_extensions"),
    "ha": ("tone", "boko_and_ajami", "verbal_aspect"),
    "so": ("nominal_inflection", "agreement", "regional_varieties"),
    "mg": ("voice", "word_order", "regional_varieties"),
    "id": ("reduplication", "affixation", "regional_varieties"),
    "ms": ("reduplication", "affixation", "jawi_orthography"),
    "tl": ("focus_voice", "reduplication", "filipino_standard_relationship"),
    "am": ("root_pattern", "agreement", "ethiopic_orthography"),
}
REQUIRED = frozenset(("record_id", "language_id", "lemma", "meaning", "variant",
                       "source_id", "publisher", "community", "speaker_consent_ref",
                       "license", "rights_url"))
MAX_LINE_BYTES = 16_384
MAX_SHARD_ROWS = 2_000
MAX_SHARD_BYTES = 40 * 1024 * 1024
MAX_SOURCE_ROW_INDEX = 10_000
SOURCE_ROW_FIELDS = ("record_id", "language_id", "lemma", "meaning", "variant")
ROW_EVIDENCE_FIELDS = frozenset(("source_row_index", "source_row_sha256"))
# These are review categories, not an assertion of productive grammar support.
LANGUAGE_FEATURES = {
    "noun_class": frozenset(("sw", "zu", "xh", "rw", "sn")),
    "class_agreement": frozenset(("sw", "zu", "xh", "rw", "sn")),
    "verbal_extension": frozenset(("sw", "zu", "xh", "rw", "sn")),
    "tone": frozenset(("yo", "ig", "ha")),
    "tone_orthography": frozenset(("yo", "ig", "ha")),
    "nominal_inflection": frozenset(("so", "am")),
    "root_pattern": frozenset(("am",)),
    "reduplication": frozenset(("id", "ms", "tl", "mg")),
    "affixation": frozenset(("id", "ms", "tl", "mg", "sw", "zu", "xh", "rw", "sn")),
    "focus_voice": frozenset(("tl", "mg")),
}
ANNOTATION_KEYS = frozenset(("feature", "label", "attested_form", "locator"))
TONE_MARKS = frozenset(("\u0300", "\u0301", "\u0302", "\u0304", "\u030c", "\u030d"))


class EvidenceError(ValueError):
    """Invalid or conflicting evidence; never downgrade to approval."""


def _unique_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise EvidenceError("duplicate JSON key")
        out[key] = value
    return out


def _load(path):
    with Path(path).open("r", encoding="utf-8", errors="strict") as handle:
        return json.load(handle, object_pairs_hook=_unique_pairs)


def _clean_string(value, *, required=False):
    if not isinstance(value, str) or (required and not value.strip()):
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return False
    return all((ord(c) >= 32 or c in "\t\n") and c != "\ufffd" for c in value)


def _bounded_lines(path):
    """Yield one logical UTF-8 line without allocating unbounded hostile rows."""
    with Path(path).open("rb") as stream:
        while True:
            raw = stream.readline(MAX_LINE_BYTES + 1)
            if not raw:
                return
            too_large = len(raw) > MAX_LINE_BYTES
            if too_large and not raw.endswith(b"\n"):
                # Discard the remainder in bounded chunks, preserving line numbers.
                while True:
                    tail = stream.readline(MAX_LINE_BYTES + 1)
                    if not tail or tail.endswith(b"\n"):
                        break
            yield None if too_large else raw


class DiverseAudit:
    def __init__(self, root=ROOT, evidence_path=HERE / "evidence.json",
                 binding_path=HERE / "source_bindings.json"):
        self.root = Path(root)
        self.registry = _load(self.root / "catalog/language_registry.v1.json")
        self.readiness = _load(self.root / "catalog/content_readiness.v1.json")
        self.ledger = _load(self.root / "legal/ledger/sources.json")
        self.evidence = _load(evidence_path)
        self.bindings = _load(binding_path)
        languages = self.registry.get("languages", [])
        if len(languages) != 100 or len({x.get("id") for x in languages}) != 100:
            raise EvidenceError("canonical registry must contain 100 unique IDs")
        self.languages = {entry["id"]: entry for entry in languages}
        if not set(RESEARCH_FOCUS).issubset(self.languages):
            raise EvidenceError("missing registered diverse-language identity")
        if set(self.readiness.get("states", {})) != set(self.languages):
            raise EvidenceError("readiness IDs differ from registry")
        if (self.ledger.get("schema_version") != "1.0.0"
                or not isinstance(self.ledger.get("sources"), list)):
            raise EvidenceError("unsupported Route05 source ledger")
        if (self.bindings.get("schema_version") != "1.0"
                or not isinstance(self.bindings.get("bindings"), list)):
            raise EvidenceError("unsupported source-language binding manifest")
        if self.evidence.get("scope") != "structural_metadata_only_not_lexical_corpus":
            raise EvidenceError("structural evidence scope mismatch")
        facts = self.evidence.get("facts")
        if not isinstance(facts, list):
            raise EvidenceError("structural evidence facts must be a list")
        seen = set()
        for fact in facts:
            if not isinstance(fact, dict):
                raise EvidenceError("malformed structural fact")
            source = fact.get("source")
            if (fact.get("language_id") not in RESEARCH_FOCUS
                or not _clean_string(fact.get("dimension"), required=True)
                or not _clean_string(fact.get("value"), required=True)
                or not isinstance(source, dict)
                or not all(_clean_string(source.get(k), required=True)
                           for k in ("publisher", "feature_author", "original_reference", "url", "license"))
                or source.get("redistribution_scope") != "attributed_structural_metadata_only"):
                raise EvidenceError("unattributed or unscoped structural fact")
            identity = (fact["language_id"], fact["dimension"], fact["value"])
            if identity in seen:
                raise EvidenceError("duplicate structural assertion")
            seen.add(identity)
        # Reuse the real Route05 contract (nested license.id and review.reviewer).
        # The read-only gate cannot grant independent human legal approval.
        self.admission = runpy.run_path(str(ROOT / "legal/ledger/admission.py"))
        self.approved_sources = {}
        for src in self.ledger["sources"]:
            if isinstance(src, dict) and _clean_string(src.get("source_id"), required=True):
                self.approved_sources.setdefault(src["source_id"], []).append(src)
        self.source_blockers = {}

    def _source_issues(self, source):
        sid = source["source_id"]
        if sid not in self.source_blockers:
            self.source_blockers[sid] = self.admission["evaluate"](
                {"schema_version": "1.0.0", "sources": [source]},
                {"languages": [], "packs": []}, [], self.root)
        return self.source_blockers[sid]

    def _approved_language_binding(self, source_id, code, variant):
        matches = [item for item in self.bindings["bindings"]
                   if isinstance(item, dict) and item.get("source_id") == source_id
                   and item.get("language_id") == code and item.get("variant") == variant]
        if len(matches) != 1:
            return False
        binding = matches[0]
        if set(binding) != {"source_id", "language_id", "variant", "proof_path",
                            "proof_sha256", "review"}:
            return False
        issues = []
        self.admission["artifact"](self.root, binding["proof_path"],
                                   binding["proof_sha256"], issues, "language binding")
        self.admission["manual_review"](binding["review"], issues, "language binding")
        return not issues

    @staticmethod
    def _annotation_reasons(code, annotation):
        if not isinstance(annotation, dict) or set(annotation) != ANNOTATION_KEYS:
            return ["incomplete_attested_analysis"]
        if not all(_clean_string(v, required=True) and len(v) <= 512
                   for v in annotation.values()):
            return ["incomplete_attested_analysis"]
        feature = annotation["feature"]
        if code not in LANGUAGE_FEATURES.get(feature, ()):
            return ["unsupported_language_feature"]
        if feature == "tone_orthography":
            nfd = unicodedata.normalize("NFD", annotation["attested_form"])
            if not any(char in TONE_MARKS for char in nfd):
                return ["unmarked_tone_surface"]
        return []

    def profile(self, code):
        if code not in RESEARCH_FOCUS:
            raise EvidenceError("uncovered or aliased language")
        entry = self.languages[code]
        facts = [f for f in self.evidence["facts"] if f["language_id"] == code]
        return {
            "language_id": code,
            "name": entry["display_names"]["en"],
            "native_name": entry["native_name"],
            "scripts": entry["scripts"],
            "related_varieties_not_aliases": entry.get("dialects", []),
            "research_focus_not_verified": list(RESEARCH_FOCUS[code]),
            "provisional_registry_features": entry["morphology"].get("features", []),
            "provisional_status": entry["morphology"].get("review_status"),
            "verified_structural_facts": facts,
            "lexical_packs_verified": False,
        }

    def _source_row_attests(self, source, candidate):
        """Require exact row bytes and lexical identity, never a file hash alone."""
        index = candidate.get("source_row_index")
        expected = candidate.get("source_row_sha256")
        if (type(index) is not int or not 1 <= index <= MAX_SOURCE_ROW_INDEX
                or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)):
            return False
        retrieval = source.get("retrieval") or {}
        if not isinstance(retrieval, dict):
            return False
        relative = retrieval.get("artifact_path")
        if not isinstance(relative, str):
            return False
        path = Path(relative)
        if (path.is_absolute() or ".." in path.parts or ".git" in path.parts
                or not path.parts):
            return False
        candidate_path = self.root / path
        resolved_root = self.root.resolve()
        resolved = candidate_path.resolve()
        if (not resolved.is_relative_to(resolved_root) or not resolved.is_file()
                or candidate_path.is_symlink() or resolved.stat().st_size > MAX_SHARD_BYTES):
            return False
        for row_index, raw in enumerate(_bounded_lines(resolved), 1):
            if row_index == index:
                if raw is None or hashlib.sha256(raw).hexdigest() != expected:
                    return False
                try:
                    value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_unique_pairs)
                except (UnicodeError, ValueError, TypeError):
                    return False
                return (isinstance(value, dict) and
                        all(value.get(k) == candidate[k] for k in SOURCE_ROW_FIELDS))
        return False

    def _candidate_reasons(self, candidate):
        if (not isinstance(candidate, dict) or not REQUIRED.issubset(candidate)
                or set(candidate) - REQUIRED - {"annotation"} - ROW_EVIDENCE_FIELDS):
            return ["invalid_candidate_schema"]
        if any(not _clean_string(candidate[k], required=k not in
                                 ("community", "speaker_consent_ref")) for k in REQUIRED):
            return ["invalid_or_missing_text"]
        code = candidate["language_id"]
        reasons = []
        if code not in RESEARCH_FOCUS:
            reasons.append("uncovered_language_or_alias")
        if candidate["community"] and not candidate["speaker_consent_ref"]:
            reasons.append("missing_speaker_consent_reference")
        if candidate["community"] or candidate["speaker_consent_ref"]:
            # The pending independent community/rights intake (#88/#93/#94)
            # must validate the consent reference. A self-asserted string is not permission.
            reasons.append("community_or_speaker_rights_require_external_review")
        parts = candidate["variant"].split("-")
        if (len(parts) < 2 or parts[0] != code
            or code not in self.languages or parts[1] not in self.languages[code]["scripts"]
            or any(not part for part in parts)):
            reasons.append("unresolved_variety_or_script")
        if "annotation" in candidate:
            reasons += self._annotation_reasons(code, candidate["annotation"])
        if (type(candidate.get("source_row_index")) is not int
                or not 1 <= candidate["source_row_index"] <= MAX_SOURCE_ROW_INDEX
                or not isinstance(candidate.get("source_row_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", candidate["source_row_sha256"])):
            reasons.append("missing_row_level_source_attestation")
        matches = self.approved_sources.get(candidate["source_id"], [])
        if len(matches) != 1:
            reasons.append("source_not_uniquely_approved")
        else:
            source = matches[0]
            if source.get("kind") not in ("dictionary", "morphology") or self._source_issues(source):
                reasons.append("redistribution_rights_unverified")
            license_data = source.get("license")
            if not isinstance(license_data, dict):
                license_data = {}
            if (candidate["publisher"] != source.get("publisher")
                or candidate["license"] != license_data.get("id")
                or candidate["rights_url"] != license_data.get("evidence_url")):
                reasons.append("provenance_conflict")
            if not self._approved_language_binding(candidate["source_id"], code, candidate["variant"]):
                reasons.append("source_language_not_approved")
            if self._source_issues(source) or not self._source_row_attests(source, candidate):
                reasons.append("candidate_not_attested_by_source_row")
        return sorted(set(reasons))

    def audit_shard(self, path, *, start_line=1, max_rows=500):
        if type(start_line) is not int or not 1 <= start_line <= 1_000_000:
            raise EvidenceError("start_line outside bounded 1..1000000")
        if type(max_rows) is not int or not 1 <= max_rows <= MAX_SHARD_ROWS:
            raise EvidenceError("max_rows outside approved 1..2000 bound")
        shard = Path(path)
        if (shard.is_symlink() or not shard.is_file() or shard.stat().st_size > MAX_SHARD_BYTES):
            raise EvidenceError("oversized or unsafe shard path")
        reviews, candidates = [], {code: 0 for code in RESEARCH_FOCUS}
        admissible = {code: 0 for code in RESEARCH_FOCUS}
        spellings = {}
        record_ids = {}
        processed, next_line = 0, start_line
        for line_no, raw in enumerate(_bounded_lines(shard), 1):
            if line_no < start_line:
                continue
            if processed >= max_rows:
                break
            processed += 1
            next_line = line_no + 1
            reasons = []
            if raw is None:
                reasons = ["oversized_line"]
                item = None
            else:
                try:
                    item = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_unique_pairs)
                    reasons = self._candidate_reasons(item)
                except (UnicodeError, ValueError, TypeError):
                    item, reasons = None, ["invalid_json_or_unicode"]
            if (isinstance(item, dict) and REQUIRED.issubset(item)
                    and not (set(item) - REQUIRED - {"annotation"} - ROW_EVIDENCE_FIELDS)
                    and all(_clean_string(item[k], required=k not in
                            ("community", "speaker_consent_ref")) for k in REQUIRED)):
                code = item["language_id"]
                if code in candidates:
                    candidates[code] += 1
                rid = (code, item["record_id"])
                signature = (item["lemma"], item["meaning"], item["variant"], item["source_id"],
                             json.dumps(item.get("annotation"), sort_keys=True, ensure_ascii=False))
                if rid in record_ids and record_ids[rid] != signature:
                    reasons.append("record_id_conflict")
                record_ids[rid] = signature
                # Unicode normalization is comparison-only, never output rewriting.
                key = (code, unicodedata.normalize("NFC", item["lemma"]).casefold(), item["variant"])
                seen = spellings.setdefault(key, set())
                if seen and (item["lemma"], item["meaning"], item["source_id"]) not in seen:
                    reasons.append("spelling_meaning_or_provenance_conflict")
                seen.add((item["lemma"], item["meaning"], item["source_id"]))
                if not reasons and code in admissible:
                    admissible[code] += 1
            if reasons:
                reviews.append({"line": line_no,
                                "language_id": (item.get("language_id") if isinstance(item, dict)
                                                and isinstance(item.get("language_id"), str)
                                                and item.get("language_id") in RESEARCH_FOCUS else None),
                                "reasons": sorted(set(reasons))})
        return {"schema_version": "1.0", "start_line": start_line, "next_line": next_line,
                "processed": processed, "candidate_counts": candidates,
                "admissible_candidate_counts_not_published": admissible,
                "review_queue": reviews, "cross_shard_conflicts": "require_separate_merge_review"}

    def report(self, audit=None):
        audit = audit or {}
        reports = {}
        unresolved = []
        for code in RESEARCH_FOCUS:
            valid_bindings = set()
            for binding in self.bindings["bindings"]:
                if not isinstance(binding, dict) or binding.get("language_id") != code:
                    continue
                sid = binding.get("source_id")
                sources = self.approved_sources.get(sid, [])
                if (len(sources) == 1 and sources[0].get("kind") in ("dictionary", "morphology")
                    and not self._source_issues(sources[0])
                    and self._approved_language_binding(sid, code, binding.get("variant"))):
                    valid_bindings.add((sid, binding["variant"]))
            if not valid_bindings:
                unresolved.append(code)
            reports[code] = {
                "content_readiness": self.readiness["states"][code],
                "verified_lexemes_in_production": (0 if self.readiness["states"][code] == "unverified" else None),
                "candidate_rows_examined": audit.get("candidate_counts", {}).get(code, 0),
                "admissible_candidate_rows_not_published": audit.get("admissible_candidate_counts_not_published", {}).get(code, 0),
                "verified_structural_fact_count": len(self.profile(code)["verified_structural_facts"]),
                "source_entries_claiming_approval": sum(
                    1 for binding in self.bindings["bindings"]
                    if isinstance(binding, dict) and binding.get("language_id") == code
                    and any(isinstance(source, dict)
                            and source.get("source_id") == binding.get("source_id")
                            and source.get("status") == "APPROVED_FOR_REDISTRIBUTION"
                            for source in self.ledger["sources"])),
                "independently_verified_language_source_bindings": len(valid_bindings),
                "unresolved_source": ("no canonical-rights-approved language/variety binding"
                                      if not valid_bindings else "requires independent production validation"),
            }
        return {"schema_version": "1.0", "reports": reports,
                "ledger_sources_total": len(self.ledger["sources"]),
                "unresolved_language_ids": unresolved,
                "discovery_catalogs_not_corpus_approval": self.evidence["discovery_sources"],
                "review_queue": audit.get("review_queue", [])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=sorted(RESEARCH_FOCUS))
    parser.add_argument("--input", type=Path, help="local evidence candidates JSONL (read-only)")
    parser.add_argument("--start-line", type=int, default=1)
    parser.add_argument("--max-rows", type=int, default=500)
    args = parser.parse_args()
    worker = DiverseAudit()
    audit = worker.audit_shard(args.input, start_line=args.start_line, max_rows=args.max_rows) if args.input else None
    output = worker.profile(args.language) if args.language else worker.report(audit)
    if audit:
        output = {"result": output, "checkpoint": audit["next_line"], "shard": audit}
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
