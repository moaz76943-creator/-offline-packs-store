"""Rebuild source-attested REVIEW_REQUIRED candidates from pinned derived harvest snapshots.

This is NOT original Wikidata Lexeme JSON or Route 05 source approval.
"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FOLDER = Path("legal/ledger/evidence/agent-harvest-20261024")
QID = re.compile(r"Q[1-9][0-9]*\Z")
LEX = re.compile(r"L[1-9][0-9]*\Z")
SENSE = re.compile(r"L[1-9][0-9]*-S[1-9][0-9]*\Z")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise ValueError("duplicate JSON property")
            obj[key] = value
        return obj
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))


def safe_file(root, relative):
    if not isinstance(relative, str):
        raise ValueError("invalid evidence path")
    parts = Path(relative)
    if parts.is_absolute() or not parts.parts or ".." in parts.parts or "\\" in relative:
        raise ValueError("unsafe evidence path")
    root = Path(root).resolve()
    current = root
    for part in parts.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("symlinked evidence")
    resolved = current.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("missing or escaping evidence")
    return resolved


def build(root, receipt, folder=FOLDER):
    root = Path(root)
    if (receipt.get("schema_version") != 1 or receipt.get("status") != "REVIEW_REQUIRED"
            or receipt.get("production_ready") is not False
            or receipt.get("source_admission_approved") is not False):
        raise ValueError("unapproved source must remain review-only")
    # A self-reported license or source path is not legal/provenance evidence.
    if (not isinstance(receipt.get("source_commit"), str)
            or not re.fullmatch(r"[0-9a-f]{40}", receipt["source_commit"])
            or receipt.get("source_branch") != "agents/data"
            or receipt.get("source_license") != "CC0-1.0"
            or receipt.get("original_lexeme_json_pinned") is not False):
        raise ValueError("invalid derived-harvest provenance")
    if (receipt.get("source_license_evidence_path")
            != "legal/source_evidence/wikidata-structured-cc0.txt"
            or receipt.get("source_license_evidence_sha256")
            != "234e955b1d8e8b1c58f0b5f7b78f439a465f4badaeabe2ddacedc7d977ca71e6"):
        raise ValueError("untrusted source license notice")
    if not isinstance(receipt.get("source_files"), list) or not receipt["source_files"]:
        raise ValueError("missing source evidence")
    # A suspected source/sense mismatch is a hard, explicit candidate-level hold.
    # Derived-harvest structure alone never constitutes independent language QA.
    qa_hold = receipt.get("linguistic_qa_status")
    if qa_hold is None:
        if "linguistic_qa_note" in receipt or "linguistic_qa_evidence" in receipt:
            raise ValueError("incomplete linguistic QA hold")
    elif (qa_hold != "SUSPECT_MISMATCH"
          or not isinstance(receipt.get("linguistic_qa_note"), str)
          or len(receipt["linguistic_qa_note"].strip()) < 20
          or not isinstance(receipt.get("linguistic_qa_evidence"), list)
          or not receipt["linguistic_qa_evidence"]
          or any(not isinstance(url, str) or not url.startswith("https://")
                 for url in receipt["linguistic_qa_evidence"])):
        raise ValueError("invalid or unsupported linguistic QA hold")
    notice = safe_file(root, receipt["source_license_evidence_path"]).read_bytes()
    if (digest(notice) != receipt["source_license_evidence_sha256"]
            or b"Lexeme and EntitySchema namespaces ONLY." not in notice
            or b"CC0-1.0" not in notice):
        raise ValueError("Wikidata Lexeme CC0 notice mismatch")
    rows, seen = [], set()
    for source in receipt["source_files"]:
        relative = source["path"]
        if not relative.startswith(str(folder) + "/sources/"):
            raise ValueError("untrusted snapshot location")
        raw = safe_file(root, relative).read_bytes()
        if digest(raw) != source["sha256"]:
            raise ValueError("source SHA256 mismatch")
        git_blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if git_blob != source["origin_git_blob_sha1"]:
            raise ValueError("origin Git blob mismatch")
        data = strict_json(raw)
        selected = source.get("selected_sense_ids")
        if selected is not None and (not isinstance(selected, list) or not selected
                or any(not isinstance(x, str) or not SENSE.fullmatch(x) for x in selected)
                or len(set(selected)) != len(selected)):
            raise ValueError("invalid selected source senses")
        selected_found = set()
        lang, topic = source["language"], source["topic"]
        if (not isinstance(lang, str) or not re.fullmatch(r"[a-z]{2,3}", lang)
                or not isinstance(topic, str) or not re.fullmatch(r"[a-z_]+", topic)
                or source.get("origin_path")
                != f"data/agents/harvest/wikidata/{lang}/{topic}.json"):
            raise ValueError("source origin path does not match language/topic")
        if (data.get("schema_version") != "1.0.0" or data.get("source") != "harvest-wikidata"
                or data.get("language") != lang or data.get("section") != topic
                or not isinstance(data.get("rows"), list) or len(data["rows"]) != source["rows"]):
            raise ValueError("source identity mismatch")
        for r in data["rows"]:
            record, sense, qid = r.get("record_id"), r.get("sense_id"), r.get("wikidata")
            if (r.get("status") != "keep" or r.get("language") != lang or r.get("section") != topic
                    or r.get("source_id") != "wikidata.lexemes" or r.get("license_id") != "CC0-1.0"
                    or not isinstance(record, str) or not LEX.fullmatch(record)
                    or not isinstance(sense, str) or not SENSE.fullmatch(sense)
                    or sense.split("-")[0] != record or not isinstance(qid, str) or not QID.fullmatch(qid)
                    or qid not in r.get("qids", []) or r.get("concept_id") != "concept." + qid.lower()
                    or r.get("origin_url") != "https://www.wikidata.org/wiki/Lexeme:" + record
                    or not isinstance(r.get("revision"), str) or not r["revision"].isdigit()
                    or not isinstance(r.get("retrieval_date"), str)
                    or not re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", r["retrieval_date"])
                    or not isinstance(r.get("lemma"), str) or not r["lemma"].strip()
                    or not isinstance(r.get("forms"), list)
                    or any(not isinstance(f, str) or not f.strip() for f in r["forms"])):
                raise ValueError("invalid harvested lexical identity")
            if selected is not None:
                if sense not in selected:
                    continue
                selected_found.add(sense)
            key = (lang, record, sense, r["concept_id"])
            if key in seen:
                raise ValueError("duplicate candidate")
            seen.add(key)
            rows.append({
                "id": ":".join((lang, record, sense, r["concept_id"])),
                "language": lang, "topic": topic, "subtopic": r.get("subsection"),
                "concept_id": r["concept_id"], "wikidata": qid,
                "lexeme_id": record, "sense_id": sense, "lemma": r["lemma"],
                "forms": list(dict.fromkeys(r["forms"])), "revision": r["revision"],
                "retrieval_date": r["retrieval_date"], "source_id": "wikidata.lexemes",
                "license_id": "CC0-1.0", "origin_url": r["origin_url"],
                "source_snapshot": relative, "source_snapshot_sha256": source["sha256"],
                "level": "UNKNOWN", "level_evidence": None,
                "directed_translations": [], "examples": [], "review_status": "REVIEW_REQUIRED",
            })
            if qa_hold == "SUSPECT_MISMATCH":
                rows[-1]["linguistic_qa_status"] = qa_hold
                rows[-1]["eligible_for_promotion"] = False
        if selected is not None and selected_found != set(selected):
            raise ValueError("selected source sense missing from snapshot")
    rows.sort(key=lambda r: (r["language"], r["topic"], r["lexeme_id"], r["sense_id"], r["concept_id"]))
    if len(rows) != receipt["actual_rows"]:
        raise ValueError("candidate count mismatch")
    return {"schema_version": 1, "source_commit": receipt["source_commit"],
            "review_status": "REVIEW_REQUIRED", "production_ready": False,
            "actual_rows": len(rows), "candidates": rows}


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


if __name__ == "__main__":
    receipt = strict_json(safe_file(ROOT, str(FOLDER / "receipt.json")).read_bytes())
    saved = safe_file(ROOT, str(FOLDER / "candidates.json")).read_bytes()
    if canonical(build(ROOT, receipt)) != saved or digest(saved) != receipt["candidate_sha256"]:
        raise SystemExit("FAIL: review-only candidate export differs from pinned source")
    print("PASS: review-only candidates =", receipt["actual_rows"])
