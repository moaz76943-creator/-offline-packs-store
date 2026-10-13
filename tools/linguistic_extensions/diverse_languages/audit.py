"""Evidence-gated, bounded review of typologically diverse language candidates.

No language substitution, inferred paradigms, network downloads, or corpus publishing.
Only standard-library dependencies. Independent of pending PR #88/#93/#94.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
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
MAX_ROW_REFERENCE = 10_000
OPTIONAL = frozenset(("source_row_index", "source_row_sha256"))


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


class DiverseAudit:
    def __init__(self, root=ROOT, evidence_path=HERE / "evidence.json"):
        self.root = Path(root)
        self.registry = _load(self.root / "catalog/language_registry.v1.json")
        self.readiness = _load(self.root / "catalog/content_readiness.v1.json")
        self.ledger = _load(self.root / "legal/ledger/sources.json")
        self.evidence = _load(evidence_path)
        languages = self.registry.get("languages", [])
        if len(languages) != 100 or len({x.get("id") for x in languages}) != 100:
            raise EvidenceError("canonical registry must contain 100 unique IDs")
        self.languages = {entry["id"]: entry for entry in languages}
        if not set(RESEARCH_FOCUS).issubset(self.languages):
            raise EvidenceError("missing registered diverse-language identity")
        if set(self.readiness.get("states", {})) != set(self.languages):
            raise EvidenceError("readiness IDs differ from registry")
        if not isinstance(self.ledger.get("sources"), list):
            raise EvidenceError("missing source ledger")
        if self.evidence.get("scope") != "structural_metadata_only_not_lexical_corpus":
            raise EvidenceError("structural evidence scope mismatch")
        for fact in self.evidence.get("facts", []):
            source = fact.get("source", {})
            if (fact.get("language_id") not in RESEARCH_FOCUS
                or not all(_clean_string(source.get(k), required=True)
                           for k in ("publisher", "feature_author", "original_reference", "url", "license"))
                or source.get("redistribution_scope") != "attributed_structural_metadata_only"):
                raise EvidenceError("unattributed or unscoped structural fact")
        self.approved_sources = {}
        for src in self.ledger["sources"]:
            if isinstance(src, dict) and src.get("source_id"):
                self.approved_sources.setdefault(src["source_id"], []).append(src)

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

    @staticmethod
    def _bounded_line(stream):
        """One physical JSONL line, even if oversized, without a large allocation."""
        result = stream.readline(MAX_LINE_BYTES + 1)
        if not result:
            return b"", False
        oversized = len(result) > MAX_LINE_BYTES
        if not result.endswith(b"\n"):
            while True:
                fragment = stream.readline(MAX_LINE_BYTES + 1)
                if not fragment:
                    break
                oversized = True
                if fragment.endswith(b"\n"):
                    break
        return (b"" if oversized else result), oversized

    def _attested_source_row(self, file, candidate):
        """Verify exact bytes AND identity against one row of the pinned source."""
        index = candidate.get("source_row_index")
        sha = candidate.get("source_row_sha256")
        if (type(index) is not int or not (1 <= index <= MAX_ROW_REFERENCE)
                or not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{64}", sha) is None):
            return False
        with file.open("rb") as stream:
            for _ in range(index):
                raw, oversized = self._bounded_line(stream)
                if not raw or oversized:
                    return False
        if hashlib.sha256(raw).hexdigest() != sha:
            return False
        try:
            row = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_unique_pairs)
        except (ValueError, UnicodeError, TypeError):
            return False
        return isinstance(row, dict) and all(
            row.get(field) == candidate[field]
            for field in ("record_id", "language_id", "lemma", "meaning", "variant")
        )

    def _candidate_reasons(self, candidate):
        reasons = []
        if (not isinstance(candidate, dict) or not REQUIRED.issubset(candidate)
                or set(candidate) - (REQUIRED | OPTIONAL)):
            return ["invalid_candidate_schema"]
        if any(not _clean_string(candidate[k], required=k not in ("community", "speaker_consent_ref"))
               for k in REQUIRED):
            return ["invalid_or_missing_text"]
        code = candidate["language_id"]
        if code not in RESEARCH_FOCUS:
            reasons.append("uncovered_language_or_alias")
        if candidate["community"]:
            # The pending independent community review/consent gate owns approvals.
            reasons.append("community_consent_not_independently_approved")
            if not candidate["speaker_consent_ref"]:
                reasons.append("missing_speaker_consent_reference")
        if candidate["variant"] == "auto":
            reasons.append("unresolved_variety_or_script")
        if (type(candidate.get("source_row_index")) is not int
            or not 1 <= candidate["source_row_index"] <= MAX_ROW_REFERENCE
            or not isinstance(candidate.get("source_row_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", candidate["source_row_sha256"]) is None):
            reasons.append("missing_row_level_source_attestation")
        matches = self.approved_sources.get(candidate["source_id"], [])
        if len(matches) != 1:
            reasons.append("source_not_uniquely_approved")
        else:
            source = matches[0]
            retrieval = source.get("retrieval") or {}
            artifact = retrieval.get("artifact_path", "")
            sha = retrieval.get("sha256", "")
            proof_ok = False
            attested = False
            if (isinstance(artifact, str)
                and artifact.startswith("tools/gha_factory/admission/")
                and isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha)):
                file = (self.root / artifact).resolve()
                if (file.is_relative_to(self.root.resolve()) and file.is_file()
                        and not file.is_symlink() and file.stat().st_size <= MAX_SHARD_BYTES):
                    digest = hashlib.sha256()
                    with file.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(65536), b""):
                            digest.update(chunk)
                    proof_ok = digest.hexdigest() == sha
                    if proof_ok:
                        attested = self._attested_source_row(file, candidate)
            review = source.get("review") or {}
            if (source.get("status") != "APPROVED_FOR_REDISTRIBUTION"
                or not isinstance(review, dict) or not review.get("approved_by")
                or not proof_ok or not source.get("license") or not source.get("rights_url")):
                reasons.append("redistribution_rights_unverified")
            if not attested:
                reasons.append("candidate_not_attested_by_source_row")
            if (candidate["publisher"] != source.get("publisher")
                or candidate["license"] != source.get("license")
                or candidate["rights_url"] != source.get("rights_url")):
                reasons.append("provenance_conflict")
            if not isinstance(source.get("languages"), list) or code not in source["languages"]:
                reasons.append("source_language_not_approved")
        return reasons

    def audit_shard(self, path, *, start_line=1, max_rows=500):
        if type(start_line) is not int or not 1 <= start_line <= 1_000_000:
            raise EvidenceError("start_line must be in 1..1000000")
        if type(max_rows) is not int or not 1 <= max_rows <= MAX_SHARD_ROWS:
            raise EvidenceError("max_rows outside approved 1..2000 bound")
        target = Path(path)
        if (target.is_symlink() or not target.is_file()
                or target.stat().st_size > MAX_SHARD_BYTES):
            raise EvidenceError("untrusted input path or oversized shard")
        reviews, candidates = [], {code: 0 for code in RESEARCH_FOCUS}
        admissible = {code: 0 for code in RESEARCH_FOCUS}
        spellings = {}
        record_ids = {}
        processed, next_line = 0, start_line
        with target.open("rb") as stream:
            line_no = 0
            while True:
                raw, oversized = self._bounded_line(stream)
                if not raw and not oversized:
                    break
                line_no += 1
                if line_no < start_line:
                    continue
                if processed >= max_rows:
                    break
                processed += 1
                next_line = line_no + 1
                reasons = []
                if oversized:
                    reasons, item = ["oversized_line"], None
                else:
                    try:
                        item = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_unique_pairs)
                        reasons = self._candidate_reasons(item)
                    except (UnicodeError, ValueError, TypeError):
                        item, reasons = None, ["invalid_json_or_unicode"]
                safe_text = (isinstance(item, dict) and REQUIRED.issubset(item)
                             and all(_clean_string(item[k], required=True)
                                     for k in ("record_id", "language_id", "lemma",
                                               "meaning", "variant", "source_id")))
                if safe_text:
                    code = item["language_id"]
                    if code in candidates:
                        candidates[code] += 1
                    rid = (code, item["record_id"])
                    signature = (item["lemma"], item["meaning"], item["variant"], item["source_id"])
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
                    lang = item.get("language_id") if isinstance(item, dict) else None
                    reviews.append({"line": line_no,
                                    "language_id": lang if isinstance(lang, str) and lang in RESEARCH_FOCUS else None,
                                    "reasons": sorted(set(reasons))})
        return {"schema_version": "1.0", "start_line": start_line, "next_line": next_line,
                "processed": processed, "candidate_counts": candidates,
                "admissible_candidate_counts_not_published": admissible,
                "review_queue": reviews, "cross_shard_conflicts": "require_separate_merge_review"}

    def report(self, audit=None):
        audit = audit or {}
        reports = {}
        for code in RESEARCH_FOCUS:
            sources = [s for s in self.ledger["sources"]
                       if isinstance(s, dict) and code in s.get("languages", [])
                       and s.get("status") == "APPROVED_FOR_REDISTRIBUTION"]
            reports[code] = {
                "content_readiness": self.readiness["states"][code],
                "verified_lexemes_in_production": (0 if self.readiness["states"][code] == "unverified" else None),
                "candidate_rows_examined": audit.get("candidate_counts", {}).get(code, 0),
                "admissible_candidate_rows_not_published": audit.get("admissible_candidate_counts_not_published", {}).get(code, 0),
                "verified_structural_fact_count": len(self.profile(code)["verified_structural_facts"]),
                "source_entries_claiming_approval": len(sources),
                "unresolved_source": "no approved source" if not sources else "requires independent production validation",
            }
        return {"schema_version": "1.0", "reports": reports,
                "ledger_sources_total": len(self.ledger["sources"]),
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
