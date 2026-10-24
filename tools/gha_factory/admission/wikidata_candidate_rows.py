"""Flatten verified Wikidata review inventory into independently keyed lexical rows.

Review-only export. No ledger admission, inferred CEFR, translations, examples,
production manifest edits, or authorization to redistribute.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from .review_only_wikidata import (
    DEFAULT_CANDIDATE, ReviewError, _decode, build, confined,
)

DEFAULT_ROWS = "legal/ledger/evidence/wikidata-20261023/lexical-row-candidates.v1.json"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_LEX = re.compile(r"L[1-9][0-9]*\Z")
_QID = re.compile(r"Q[1-9][0-9]*\Z")


def _require(condition, reason):
    if not condition:
        raise ReviewError(reason)


def flatten(inventory):
    """Preserve attested lexeme/sense/form identity, one row per real entity."""
    _require(isinstance(inventory, dict) and
             inventory.get("status") == "REVIEW_REQUIRED" and
             inventory.get("publication_approved") is False, "not review-only inventory")
    entries = inventory.get("lexemes")
    _require(isinstance(entries, list) and bool(entries), "missing lexical inventory")
    rows, seen = [], set()
    counts = {"lexemes": 0, "senses": 0, "forms": 0, "attested_concept_links": 0,
              "attested_grammar_feature_links": 0}
    languages = set()
    for entry in entries:
        _require(isinstance(entry, dict), "invalid lexeme")
        lid = entry.get("entity_id")
        _require(isinstance(lid, str) and _LEX.fullmatch(lid), "invalid lexeme ID")
        _require(entry.get("source_status") == "REVIEW_REQUIRED" and
                 entry.get("publication_approved") is False and
                 entry.get("license_id") == "CC0-1.0", "unreviewed rights/status")
        _require(all(isinstance(entry.get(key), str) and _SHA.fullmatch(entry[key])
                     for key in ("source_artifact_sha256", "license_evidence_sha256")),
                 "missing pinned evidence")
        _require(entry.get("topic_status") == "UNASSIGNED" and
                 entry.get("level_status") == "UNKNOWN" and
                 entry.get("directed_translations") == [] and
                 entry.get("examples") == [], "unsupported enrichment")
        language = entry.get("language")
        _require(isinstance(language, str) and language, "missing language")
        _require(isinstance(entry.get("lemma"), str) and entry["lemma"].strip() and
                 isinstance(entry.get("lexical_category_qid"), str) and
                 _QID.fullmatch(entry["lexical_category_qid"]), "invalid attested lexeme")
        languages.add(language)
        common = {
            "lexeme_id": lid, "language": language,
            "source_id": entry["source_id"], "source_artifact_sha256": entry["source_artifact_sha256"],
            "license_id": "CC0-1.0", "license_evidence_sha256": entry["license_evidence_sha256"],
            "source_status": "REVIEW_REQUIRED", "publication_approved": False,
            "topic_id": None, "subtopic_id": None, "scenario_id": None,
            "intent_id": None, "skill_id": None, "grammar_id": None,
            "level": "UNKNOWN", "level_framework": "UNKNOWN",
        }
        def add(kind, identity, data):
            _require(identity not in seen, "duplicate lexical entity ID")
            seen.add(identity)
            rows.append({**common, "row_type": kind, "row_id": identity, "attested": data})
        add("lexeme", lid, {
            "lemma": entry["lemma"], "lexical_category_qid": entry["lexical_category_qid"],
            "language_qid": entry["language_qid"], "revision": entry["revision"],
        })
        counts["lexemes"] += 1
        senses, forms = entry.get("senses"), entry.get("forms")
        _require(isinstance(senses, list) and isinstance(forms, list), "missing senses/forms")
        for sense in senses:
            sid = sense.get("sense_id") if isinstance(sense, dict) else None
            _require(isinstance(sid, str) and re.fullmatch(re.escape(lid) + r"-S[1-9][0-9]*", sid),
                     "invalid sense ID")
            glosses, concepts = sense.get("attested_glosses"), sense.get("attested_concept_qids")
            _require(isinstance(glosses, dict) and bool(glosses) and
                     all(isinstance(k, str) and k and isinstance(v, str) and v.strip()
                         for k, v in glosses.items()), "missing attested gloss")
            _require(isinstance(concepts, list) and len(concepts) == len(set(concepts)) and
                     all(isinstance(q, str) and _QID.fullmatch(q) for q in concepts),
                     "invalid attested concept")
            add("sense", sid, {"glosses": glosses, "concept_qids": concepts})
            counts["senses"] += 1
            counts["attested_concept_links"] += len(concepts)
            # P5137 is an explicit source-attested sense-to-item assertion,
            # not a directed translation or proof of a broader concept graph.
            # Give each assertion its own stable row without cloning the sense.
            for concept_qid in concepts:
                add("concept_link", f"{sid}:P5137:{concept_qid}", {
                    "sense_id": sid, "property_id": "P5137",
                    "concept_qid": concept_qid,
                })
        for form in forms:
            fid = form.get("form_id") if isinstance(form, dict) else None
            _require(isinstance(fid, str) and re.fullmatch(re.escape(lid) + r"-F[1-9][0-9]*", fid),
                     "invalid form ID")
            features = form.get("grammatical_feature_qids")
            _require(isinstance(form.get("surface"), str) and form["surface"].strip() and
                     isinstance(features, list) and
                     all(isinstance(q, str) and _QID.fullmatch(q) for q in features),
                     "invalid attested form")
            _require(len(features) == len(set(features)),
                     "duplicate attested grammatical feature")
            add("form", fid, {"surface": form["surface"], "grammatical_feature_qids": features})
            counts["forms"] += 1
            # Each QID is an independently traceable assertion in the original
            # form's grammaticalFeatures array, not an inferred conjugation.
            # The form itself is stored only once; zero-feature forms add none.
            for feature_qid in features:
                add("form_grammar_feature", f"{fid}:grammaticalFeature:{feature_qid}", {
                    "form_id": fid, "grammatical_feature_qid": feature_qid,
                })
                counts["attested_grammar_feature_links"] += 1
    expected = inventory.get("summary")
    _require(isinstance(expected, dict) and
             all(expected.get(key) == counts[key] for key in
                 ("lexemes", "senses", "forms", "attested_concept_links")) and
             expected.get("languages") == sorted(languages), "inventory count mismatch")
    return {
        "schema_version": "1.0.0", "status": "REVIEW_REQUIRED",
        "publication_approved": False,
        "source_dossier": inventory["source_dossier"],
        "summary": {**counts, "actual_rows": len(rows), "languages": sorted(languages)},
        "rows": rows,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--output", default=DEFAULT_ROWS)
    parser.add_argument("--write-new", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = args.repo_root.resolve()
        original = build(root)
        if _decode(confined(root, DEFAULT_CANDIDATE).read_bytes()) != original:
            raise ReviewError("inventory differs from pinned source")
        expected = flatten(original)
        output = confined(root, args.output)
        if args.write_new:
            if output.exists() or output.is_symlink():
                raise ReviewError("candidate rows already exist")
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as handle:
                json.dump(expected, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        elif _decode(output.read_bytes()) != expected:
            raise ReviewError("candidate rows differ from pinned original evidence")
    except (ReviewError, OSError, KeyError, TypeError, ValueError) as exc:
        print("REVIEW_ROWS_BLOCKED:", str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"status": "REVIEW_REQUIRED", **expected["summary"],
                      "publication_approved": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
