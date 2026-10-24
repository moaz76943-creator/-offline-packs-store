"""Reproducible, review-only Wikidata lexical inventory from pinned source bytes.

Never changes the source ledger, queue, manifest, or publication status.
It is deliberately NOT a replacement for independent Route 05 admission.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from tools.gha_factory.admission.verified_snapshot import license_notice

QID = re.compile(r"Q[1-9][0-9]*\Z")
LEXEME = re.compile(r"L[1-9][0-9]*\Z")
VERSION = re.compile(r"l([1-9][0-9]*)-r([1-9][0-9]*)\Z")
MAX_EVIDENCE = 1024 * 1024
DEFAULT_DOSSIER = "legal/ledger/evidence/wikidata-20261023"
DEFAULT_CANDIDATE = DEFAULT_DOSSIER + "/lexical-candidates.v1.json"


class ReviewError(ValueError):
    pass


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ReviewError("duplicate JSON key")
        result[key] = value
    return result


def _decode(data):
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ReviewError("nonfinite JSON")))
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ReviewError("invalid source JSON") from exc


def checked(root, relative, digest, limit=MAX_EVIDENCE):
    """Hash real bounded bytes; reject traversal and symlink components."""
    if not isinstance(relative, str) or not relative or not isinstance(digest, str):
        raise ReviewError("missing evidence path/hash")
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ReviewError("invalid evidence SHA256")
    path = Path(relative)
    if path.is_absolute() or any(p in ("..", ".git") for p in path.parts):
        raise ReviewError("unsafe evidence path")
    current = Path(root).resolve()
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ReviewError("symlink evidence path")
    if not current.is_file() or current.stat().st_size > limit:
        raise ReviewError("missing/oversized evidence")
    raw = current.read_bytes()
    if not raw or hashlib.sha256(raw).hexdigest() != digest:
        raise ReviewError("evidence SHA256 mismatch")
    return raw


def _entity_record(source, root, languages, receipt_row):
    match = VERSION.fullmatch(source.get("dataset_version", ""))
    if not match:
        raise ReviewError("invalid pinned revision")
    lexeme_id, revision = "L" + match[1], int(match[2])
    origin = urlsplit(source.get("origin_url", ""))
    if (origin.scheme != "https" or origin.netloc != "www.wikidata.org"
            or origin.path != "/wiki/Special:EntityData/" + lexeme_id + ".json"
            or parse_qs(origin.query) != {"revision": [str(revision)]} or origin.fragment):
        raise ReviewError("unreviewed Wikidata entity URL")
    if source.get("status") != "REVIEW_REQUIRED" or source.get("kind") != "dictionary":
        raise ReviewError("source must remain review-only")
    if source.get("source_id") != "wikidata-lexeme-" + match[0]:
        raise ReviewError("source identity mismatch")
    license_data = source.get("license") or {}
    if license_data.get("id") != "CC0-1.0":
        raise ReviewError("unsupported source license")
    checked(root, license_data.get("evidence_path"), license_data.get("evidence_sha256"))
    license_notice(Path(root) / license_data["evidence_path"], "CC0-1.0")
    retrieval = source.get("retrieval") or {}
    if retrieval.get("identity") != f"wikidata:Lexeme:{lexeme_id}:revision:{revision}":
        raise ReviewError("retrieval identity mismatch")
    if retrieval.get("url") != source["origin_url"]:
        raise ReviewError("retrieval URL mismatch")
    raw = checked(root, retrieval.get("artifact_path"), retrieval.get("sha256"))
    document = _decode(raw)
    entities = document.get("entities") if isinstance(document, dict) else None
    if not isinstance(entities, dict) or list(entities) != [lexeme_id]:
        raise ReviewError("unexpected source entities")
    entity = entities[lexeme_id]
    if (not isinstance(entity, dict) or entity.get("type") != "lexeme"
            or entity.get("id") != lexeme_id or type(entity.get("lastrevid")) is not int
            or entity["lastrevid"] != revision):
        raise ReviewError("entity revision/type mismatch")
    language_qid = entity.get("language")
    language = languages.get(language_qid)
    if not language:
        raise ReviewError("language QID not in production registry")
    lemmas = entity.get("lemmas") or {}
    lemma_data = lemmas.get(language) if isinstance(lemmas, dict) else None
    lemma = lemma_data.get("value") if isinstance(lemma_data, dict) else None
    if not isinstance(lemma, str) or not lemma.strip():
        raise ReviewError("missing attested lemma")
    category = entity.get("lexicalCategory")
    if not isinstance(category, str) or not QID.fullmatch(category):
        raise ReviewError("invalid lexical category")
    forms = []
    for form in entity.get("forms") or []:
        if not isinstance(form, dict) or not re.fullmatch(re.escape(lexeme_id) + r"-F[1-9][0-9]*", str(form.get("id", ""))):
            raise ReviewError("invalid form identity")
        representations = form.get("representations") or {}
        representation = representations.get(language) if isinstance(representations, dict) else None
        surface = representation.get("value") if isinstance(representation, dict) else None
        features = form.get("grammaticalFeatures") or []
        if (not isinstance(surface, str) or not surface.strip()
                or not isinstance(features, list)
                or any(not isinstance(f, str) or not QID.fullmatch(f) for f in features)):
            raise ReviewError("invalid attested form")
        forms.append({"form_id": form["id"], "surface": surface,
                      "grammatical_feature_qids": features})
    senses = []
    for sense in entity.get("senses") or []:
        if not isinstance(sense, dict) or not re.fullmatch(re.escape(lexeme_id) + r"-S[1-9][0-9]*", str(sense.get("id", ""))):
            raise ReviewError("invalid sense identity")
        glosses = sense.get("glosses") or {}
        if not isinstance(glosses, dict) or not glosses:
            raise ReviewError("sense has no attested gloss")
        copied = {}
        for code, gloss in glosses.items():
            value = gloss.get("value") if isinstance(gloss, dict) else None
            if not isinstance(value, str) or not value.strip():
                raise ReviewError("invalid attested gloss")
            copied[code] = value
        senses.append({"sense_id": sense["id"], "attested_glosses": copied})
    if len({x["form_id"] for x in forms}) != len(forms) or len({x["sense_id"] for x in senses}) != len(senses):
        raise ReviewError("duplicate form/sense identity")
    if (receipt_row.get("source_id") != source["source_id"]
            or receipt_row.get("decision") != "keep"
            or receipt_row.get("accepted_lexemes") != 1
            or receipt_row.get("accepted_senses") != len(senses)
            or receipt_row.get("attested_forms") != len(forms)
            or receipt_row.get("publication_approved") is not False
            or receipt_row.get("source_evidence_verified") is not False):
        raise ReviewError("source does not match review-only QA receipt")
    return {
        "source_id": source["source_id"],
        "source_artifact_sha256": retrieval["sha256"],
        "license_evidence_sha256": license_data["evidence_sha256"],
        "license_id": "CC0-1.0",
        "source_status": "REVIEW_REQUIRED",
        "origin_url": source["origin_url"],
        "entity_id": lexeme_id,
        "revision": revision,
        "language": language,
        "language_qid": language_qid,
        "lexical_category_qid": category,
        "lemma": lemma,
        "forms": forms,
        "senses": senses,
        "topic_status": "UNASSIGNED",
        "level_status": "UNKNOWN",
        "directed_translations": [],
        "examples": [],
        "publication_approved": False,
    }


def build(root, dossier=DEFAULT_DOSSIER):
    root = Path(root).resolve()
    dossier_path = Path(dossier)
    if dossier_path.is_absolute() or ".." in dossier_path.parts:
        raise ReviewError("unsafe dossier path")
    receipt_path = root / dossier_path / "review-receipt.json"
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise ReviewError("missing review receipt")
    receipt = _decode(receipt_path.read_bytes())
    proposals = _decode(checked(root, str(dossier_path / "proposed-sources.json"),
                                receipt["proposed_sources_sha256"]))
    copyright_proof = receipt["retrievals"]["license"]
    checked(root, copyright_proof["artifact_path"], copyright_proof["sha256"])
    registry = _decode((root / "catalog/production_languages.v1.json").read_bytes())
    languages = {row["wikidata"]: row["id"] for row in registry["languages"]}
    sources = proposals.get("sources")
    receipt_rows = receipt.get("results")
    if (proposals.get("schema_version") != "1.0.0"
            or not isinstance(sources, list) or not sources
            or not isinstance(receipt_rows, list) or len(sources) != len(receipt_rows)):
        raise ReviewError("invalid source dossier")
    by_source = {r["source_id"]: r for r in receipt_rows}
    if len(by_source) != len(receipt_rows):
        raise ReviewError("duplicate review receipt source")
    records = [_entity_record(source, root, languages, by_source[source["source_id"]])
               for source in sources]
    if len({r["entity_id"] for r in records}) != len(records):
        raise ReviewError("duplicate source lexeme")
    return {
        "schema_version": "1.0.0",
        "status": "REVIEW_REQUIRED",
        "publication_approved": False,
        "source_dossier": str(dossier_path),
        "summary": {
            "lexemes": len(records),
            "senses": sum(len(r["senses"]) for r in records),
            "forms": sum(len(r["forms"]) for r in records),
            "languages": sorted({r["language"] for r in records}),
        },
        "lexemes": records,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--dossier", default=DEFAULT_DOSSIER)
    parser.add_argument("--candidate", default=DEFAULT_CANDIDATE)
    parser.add_argument("--write-new", action="store_true",
                        help="Create a new review-only inventory; never overwrite")
    args = parser.parse_args(argv)
    try:
        expected = build(args.repo_root, args.dossier)
        path = args.repo_root / args.candidate
        if args.write_new:
            if path.exists() or path.is_symlink():
                raise ReviewError("candidate already exists; refusing overwrite")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                json.dump(expected, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        elif _decode(path.read_bytes()) != expected:
            raise ReviewError("review-only inventory differs from pinned original evidence")
    except (ReviewError, OSError, KeyError, TypeError, IndexError) as exc:
        print("REVIEW_CANDIDATE_BLOCKED:", str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"status": "REVIEW_REQUIRED", **expected["summary"],
                      "publication_approved": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
