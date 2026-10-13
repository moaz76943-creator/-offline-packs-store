"""Evidence-only Germanic/Romance morphology; no unverified form generation."""
import argparse
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SHA = re.compile(r"^[0-9a-f]{64}$")
POSITIONS = frozenset(("noun", "verb", "adjective", "determiner", "multiword"))


class EvidenceError(ValueError):
    """Fail-closed language, form, provenance or paradigm contract violation."""


def read_json(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_inside(root, name):
    root = Path(root).resolve()
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or ".git" in path.parts:
        raise EvidenceError("unsafe input path")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise EvidenceError("input missing or escapes repository")
    return resolved


class EvidenceEngine:
    def __init__(self, root=ROOT, profiles_path=None, ledger_path=None):
        self.root = Path(root).resolve()
        self.profiles = read_json(profiles_path or HERE / "profiles.json")["languages"]
        registry = read_json(self.root / "catalog/language_registry.v1.json")
        identities = {item["id"]: item["family"] for item in registry["languages"]}
        if len(identities) != 100 or len(self.profiles) != 19:
            raise EvidenceError("registry/profile cardinality changed")
        for code, profile in self.profiles.items():
            if identities.get(code) != profile["registry_family"] or not profile.get("axes"):
                raise EvidenceError("profile not anchored to canonical registry: " + code)
        self.ledger = read_json(ledger_path or self.root / "legal/ledger/sources.json")
        if self.ledger.get("schema_version") != "1.0.0" or not isinstance(self.ledger.get("sources"), list):
            raise EvidenceError("invalid Route05 source ledger")
        self.sources = {}
        for item in self.ledger["sources"]:
            sid = item.get("source_id") if isinstance(item, dict) else None
            if not isinstance(sid, str) or not sid or sid in self.sources:
                raise EvidenceError("invalid/duplicate source identity")
            self.sources[sid] = item

    def eligible_source(self, source_id):
        source = self.sources.get(source_id)
        if not source or source.get("kind") != "morphology" or source.get("status") != "APPROVED_FOR_REDISTRIBUTION":
            return False
        retrieval = source.get("retrieval") or {}
        license_info = source.get("license") or {}
        review = source.get("review") or {}
        if not (review.get("reviewer") and str(review.get("decision_url", "")).startswith("https://")
                and retrieval.get("identity") and str(retrieval.get("url", "")).startswith("https://")
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(retrieval.get("date", "")))
                and source.get("publisher") and source.get("dataset_version")
                and source.get("alterations") and license_info.get("id") in
                ("CC-BY-SA-4.0", "GFDL-1.3-only", "CC0-1.0", "PUBLIC-DOMAIN")
                and str(license_info.get("evidence_url", "")).startswith("https://")
                and str(source.get("origin_url", "")).startswith("https://")):
            return False
        try:
            for path_key, hash_key, data in (("artifact_path", "sha256", retrieval),
                                             ("evidence_path", "evidence_sha256", license_info)):
                expected = data.get(hash_key)
                if not isinstance(expected, str) or not SHA.fullmatch(expected):
                    return False
                if sha256(resolve_inside(self.root, data.get(path_key, ""))) != expected:
                    return False
        except (EvidenceError, TypeError, OSError):
            return False
        if license_info["evidence_url"].startswith(("https://creativecommons.org/licenses/",
                                                     "https://creativecommons.org/publicdomain/zero/",
                                                     "https://www.gnu.org/licenses/fdl-")):
            return False
        if license_info["id"] == "PUBLIC-DOMAIN" and not all(
                (license_info.get("public_domain_proof") or {}).get(k)
                for k in ("jurisdiction", "legal_basis", "work_date")):
            return False
        return True

    def validate(self, record, language):
        if language not in self.profiles or not isinstance(record, dict):
            raise EvidenceError("unregistered/unsupported language or invalid record")
        if record.get("language_code") != language:
            raise EvidenceError("cross-language form rejected")
        for key in ("lemma_id", "sense_id"):
            value = record.get(key)
            if not isinstance(value, str) or not value.startswith(language + ":") or len(value) < len(language) + 3:
                raise EvidenceError("canonical scoped " + key + " required")
        for key in ("lemma", "form", "record_locator"):
            value = record.get(key)
            if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
                raise EvidenceError("original Unicode text/record locator required: " + key)
        if "variant_id" in record and (not isinstance(record["variant_id"], str) or not record["variant_id"].strip()):
            raise EvidenceError("invalid explicit variant identity")
        if record.get("pos") not in POSITIONS:
            raise EvidenceError("part of speech required for verifiable inventory")
        tags = record.get("features")
        axes = self.profiles[language]["axes"]
        if not isinstance(tags, dict) or not tags:
            raise EvidenceError("explicit feature evidence required")
        if language in ("no", "pt") and "variety" not in tags:
            raise EvidenceError("registered umbrella ID requires attested variety")
        for key, value in tags.items():
            if key not in axes or value not in axes[key]:
                raise EvidenceError("unsupported language-specific feature: " + str(key))
        if record.get("uncertainty") not in (None, "attested", "unresolved"):
            raise EvidenceError("invalid uncertainty state")
        if record.get("uncertainty") == "unresolved":
            raise EvidenceError("unresolved morphology cannot be verified")
        if record["pos"] == "verb" and ("compound" in tags.get("tense", "") or
                tags.get("tense") in ("perfect", "pluperfect", "present_perfect", "passe_compose",
                                      "passato_prossimo", "perfect_compus", "trapassato_prossimo",
                                      "plus_que_parfait", "perfect_periphrastic")):
            if not tags.get("auxiliary") or not record.get("components"):
                raise EvidenceError("compound form requires attested auxiliary and components")
        if record.get("components") is not None and (not isinstance(record["components"], list)
                or not record["components"] or not all(isinstance(v, str) and v for v in record["components"])):
            raise EvidenceError("invalid attested compound components")
        sid = record.get("source_id")
        source = self.sources.get(sid)
        if not source or not self.eligible_source(sid):
            raise EvidenceError("source not admitted with immutable original and license evidence")
        if (record.get("source_version") != source.get("dataset_version") or
                record.get("source_sha256") != (source.get("retrieval") or {}).get("sha256") or
                not record.get("evidence_version")):
            raise EvidenceError("source version/hash/evidence mismatch")

        # Exact immutable source-byte witness. An approved artifact hash alone
        # does not prove an invented conjugation is actually present in it.
        locator = re.fullmatch(r"byte:(0|[1-9][0-9]*):([1-9][0-9]*)",
                               record["record_locator"])
        if locator is None:
            raise EvidenceError("source attestation needs byte:offset:length locator")
        offset, length = (int(value) for value in locator.groups())
        if length > 65536:
            raise EvidenceError("source attestation slice too large")
        original = resolve_inside(self.root, source["retrieval"]["artifact_path"])
        if offset > original.stat().st_size or length > original.stat().st_size - offset:
            raise EvidenceError("source attestation outside immutable original bytes")
        try:
            with original.open("rb") as stream:
                if offset:
                    stream.seek(offset - 1)
                    if stream.read(1) != b"\\n":
                        raise EvidenceError("source attestation offset is not a row boundary")
                stream.seek(offset)
                raw_row = stream.read(length)
                if not raw_row.endswith(b"\\n"):
                    raise EvidenceError("source attestation requires an exact JSONL row")
            observed = json.loads(raw_row.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError, OSError) as exc:
            raise EvidenceError("invalid original source attestation") from exc
        keys = ("language_code", "lemma_id", "sense_id", "lemma", "form",
                "pos", "features")
        if not isinstance(observed, dict) or any(observed.get(key) != record[key]
                                                  for key in keys):
            raise EvidenceError("form has no exact source attestation")
        # Re-check immutable bytes after reading to detect mid-audit tampering.
        if not self.eligible_source(sid):
            raise EvidenceError("source attestation changed during validation")
        return record

    def audit(self, language, input_path=None, limit=100000):
        if language not in self.profiles:
            raise EvidenceError("unsupported language")
        if not isinstance(limit, int) or limit < 1 or limit > 1000000:
            raise EvidenceError("invalid bounded record limit")
        forms = set()
        seen = {}
        verbs, nouns, paradigms = set(), set(), set()
        input_hash = None
        if input_path is not None:
            path = resolve_inside(self.root, input_path)
            input_hash = sha256(path)
            with path.open(encoding="utf-8") as stream:
                for n, line in enumerate(stream, 1):
                    if n > limit:
                        raise EvidenceError("bounded shard size exceeded")
                    if len(line) > 65536:
                        raise EvidenceError("oversize morphology record")
                    if not line.strip():
                        continue
                    try:
                        record = self.validate(json.loads(line), language)
                    except (ValueError, TypeError) as exc:
                        raise EvidenceError(f"line {n}: {exc}") from exc
                    signature = (record["lemma_id"], record["sense_id"],
                                 tuple(sorted(record["features"].items())), record.get("variant_id"))
                    previous = seen.get(signature)
                    if previous is not None and previous != record["form"]:
                        raise EvidenceError("conflicting homograph/participle/auxiliary paradigm")
                    seen[signature] = record["form"]
                    forms.add((signature, record["form"]))
                    if record["pos"] == "verb":
                        verbs.add(record["lemma_id"])
                        paradigms.add((record["lemma_id"], record["sense_id"]))
                    elif record["pos"] == "noun":
                        nouns.add(record["lemma_id"])
        return {"language": language, "verified_verbs": len(verbs),
                "verified_paradigms": len(paradigms), "verified_nouns": len(nouns),
                "verified_inflections": len(forms), "input_sha256": input_hash,
                "status": "verified_source_bounded" if input_hash else "blocked_no_admitted_input"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--language", required=True)
    parser.add_argument("--input", help="repository-relative admitted JSONL morphology shard")
    parser.add_argument("--checkpoint", help="local JSON file outside production pack paths")
    args = parser.parse_args(argv)
    result = EvidenceEngine(args.root).audit(args.language, args.input)
    result_text = json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
    if args.checkpoint:
        dest = Path(args.checkpoint)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(result_text, encoding="utf-8")
    print(result_text, end="")


if __name__ == "__main__":
    main()
