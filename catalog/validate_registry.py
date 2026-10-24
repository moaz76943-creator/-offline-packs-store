#!/usr/bin/env python3
"""Stdlib-only structural and cross-file validation of the public language registry.

JSON Schema 2020-12 is supplied separately for consumers with schema tooling.
This validator additionally enforces cross-record invariants absent from JSON Schema.
"""
import argparse
import json
import jsonschema
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
TAG = re.compile(r"^[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|[0-9]{3}))?(?:-(?:[a-z0-9]{5,8}|[0-9][a-z0-9]{3}))*$")
SCRIPT = re.compile(r"^[A-Z][a-z]{3}$")
RIGHT_TO_LEFT = {"Arab", "Hebr", "Thaa", "Nkoo", "Adlm", "Syrc"}
FEATURES = {"gender", "noun_classes", "case", "number", "root_pattern", "inflection", "agglutination", "aspect", "classifiers", "tones", "honorifics", "analytic"}
STATES = {"unverified", "not_started", "in_progress", "metadataOnly", "sourceAvailable", "verifiedPack", "installedCapable", "releaseReady", "blocked", "deprecated"}


def validate(registry, readiness, manifest=None, required_count=100, source_ledger=None):
    """Return deterministic human-readable problems without mutating inputs."""
    errors = []
    def problem(message):
        errors.append(message)

    schema_path = HERE / "language_registry.schema.json"
    if schema_path.exists():
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        try:
            jsonschema.validate(instance=registry, schema=schema)
        except jsonschema.exceptions.ValidationError as e:
            problem(f"schema validation error: {e.message}")


    if registry.get("schema_version") != "1.0.0":
        problem("unsupported registry schema_version")
    if readiness.get("schema_version") != "1.0.0":
        problem("unsupported readiness schema_version")
    if readiness.get("registry_version") != registry.get("schema_version"):
        problem("readiness registry_version mismatch")
    scripts = registry.get("scripts")
    languages = registry.get("languages")
    frameworks = registry.get("frameworks")
    if not isinstance(scripts, dict) or not isinstance(languages, list) or not isinstance(frameworks, dict):
        return errors + ["scripts/languages/frameworks have invalid container types"]
    if required_count is not None and len(languages) != required_count:
        problem(f"expected {required_count} languages, found {len(languages)}")
    for code, spec in scripts.items():
        if not SCRIPT.fullmatch(code):
            problem(f"invalid ISO 15924 script syntax: {code}")
        if not isinstance(spec, dict) or spec.get("direction") not in {"ltr", "rtl", "ttb-ltr"}:
            problem(f"invalid script direction: {code}")
        elif spec["direction"] != ("ttb-ltr" if code == "Mong" else "rtl" if code in RIGHT_TO_LEFT else "ltr"):
            problem(f"{'vertical' if code == 'Mong' else 'RTL'} script-direction mismatch: {code}")
    ids = set()
    for language in languages:
        if not isinstance(language, dict):
            problem("non-object language record")
            continue
        code = language.get("id", "")
        if not isinstance(code, str) or not TAG.fullmatch(code) or "-" in code:
            problem(f"invalid stable language id: {code}")
        if code in ids:
            problem(f"duplicate language id: {code}")
        ids.add(code)
        if not isinstance(language.get("native_name"), str) or not language["native_name"].strip():
            problem(f"missing native name: {code}")
        display = language.get("display_names")
        if not isinstance(display, dict) or any(not isinstance(display.get(k), str) or not display[k].strip() for k in ("en", "ar")):
            problem(f"missing localized display name: {code}")
        if not isinstance(language.get("family"), str) or not language["family"]:
            problem(f"missing linguistic family: {code}")
        used = language.get("scripts")
        default = language.get("default_script")
        if not isinstance(used, list) or not used or len(used) != len(set(used)) or any(s not in scripts for s in used):
            problem(f"unknown or duplicated script: {code}")
        elif default not in used:
            problem(f"default script not supported: {code}")
        if not isinstance(language.get("regions"), list) or any(not re.fullmatch(r"[A-Z]{2}|[0-9]{3}", r) for r in language["regions"]):
            problem(f"invalid region list: {code}")
        if not isinstance(language.get("dialects"), list):
            problem(f"invalid dialect list: {code}")
        morph = language.get("morphology")
        if not isinstance(morph, dict) or morph.get("review_status") not in {"provisional", "reviewed"}:
            problem(f"invalid morphology classification: {code}")
        else:
            active = morph.get("features", [])
            if not isinstance(active, list) or len(active) != len(set(active)) or any(f not in FEATURES for f in active):
                problem(f"invalid morphology features: {code}")
        prof = language.get("proficiency")
        if not isinstance(prof, dict) or prof.get("mapping_status") not in {"not_mapped", "mapped", "not_applicable"}:
            problem(f"invalid proficiency state: {code}")
        elif not isinstance(prof.get("framework_ids"), list) or len(prof["framework_ids"]) != len(set(prof["framework_ids"])) or any(f not in frameworks for f in prof["framework_ids"]):
            problem(f"unknown proficiency framework: {code}")
    for fw, info in frameworks.items():
        if not isinstance(info, dict) or info.get("scale_type") not in {"general", "language_specific"} or not isinstance(info.get("levels"), list) or not info["levels"]:
            problem(f"invalid framework: {fw}")
    seen_tags = set(ids)
    for alias in registry.get("aliases", []):
        if not isinstance(alias, dict):
            problem("invalid alias record")
            continue
        src, dst = alias.get("from"), alias.get("to")
        if not isinstance(src, str) or not TAG.fullmatch(src):
            problem(f"invalid alias tag: {src}")
        if src in seen_tags:
            problem(f"alias/variant collision: {src}")
        seen_tags.add(src)
        if dst not in ids:
            problem(f"alias target missing: {src} -> {dst}")
        if alias.get("lossy") is not True or alias.get("status") != "migration_review_required":
            problem(f"unsafe unreviewed fallback alias: {src}")
    for variant in registry.get("locale_variants", []):
        if not isinstance(variant, dict):
            problem("invalid locale variant record")
            continue
        tag, code = variant.get("tag"), variant.get("language_id")
        if not isinstance(tag, str) or not TAG.fullmatch(tag):
            problem(f"invalid locale tag: {tag}")
        if tag in seen_tags:
            problem(f"alias/variant collision: {tag}")
        seen_tags.add(tag)
        lang = next((l for l in languages if l.get("id") == code), None)
        if lang is None:
            problem(f"variant language missing: {tag}")
            continue
        segments = tag.split("-") if isinstance(tag, str) else []
        if segments and segments[0] != code:
            problem(f"variant primary language mismatch: {tag}")
        script, region = variant.get("script"), variant.get("region")
        if script is not None and (script not in lang.get("scripts", []) or script not in segments):
            problem(f"variant script mismatch: {tag}")
        if region is not None and (region not in lang.get("regions", []) or region not in segments):
            problem(f"variant region mismatch: {tag}")
        if not script and not region and not variant.get("dialect"):
            problem(f"undifferentiated variant: {tag}")
    statuses = readiness.get("states")
    if not isinstance(statuses, dict) or set(statuses) != ids:
        problem("readiness states must match all and only canonical IDs")
    elif any(s not in STATES for s in statuses.values()):
        problem("invalid content readiness state")
    else:
        for code, state in statuses.items():
            if state != "releaseReady":
                continue
            evidence = readiness.get("validation_evidence", {}).get(code, {})
            if (not isinstance(evidence, dict)
                    or not isinstance(evidence.get("pack_sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", evidence.get("pack_sha256", ""))
                    or evidence.get("validation_method") not in {"automated_quality_gate", "manual_review"}):
                problem(f"releaseReady content requires independent evidence: {code}")
                continue
            # A well-formed digest alone is not proof that the pack exists or passed QA.
            if evidence.get("validation_method") != "automated_quality_gate":
                problem(f"releaseReady requires an automated quality gate: {code}")
            current_manifest = {x.get("code"): x for x in (manifest or {}).get("languages", [])
                                if isinstance(x, dict)}.get(code)
            if not current_manifest or not all(current_manifest.get(flag) is True
                    for flag in ("content_available", "pack_verified", "production_ready", "is_active")):
                problem(f"releaseReady lacks verified published pack state: {code}")
            elif (current_manifest.get("sha256") != evidence.get("pack_sha256")
                  or current_manifest.get("schemaVersion") in (None, "legacy")
                  or current_manifest.get("format") == "legacy-json-gzip"):
                problem(f"releaseReady pack hash/schema does not match publication: {code}")
            if not manifest or manifest.get("release_status") in (None, "BLOCKED_DEPENDENCY"):
                problem(f"releaseReady is blocked by global release state: {code}")
            admitted = {item.get("source_id"): item for item in (source_ledger or {}).get("sources", [])
                        if isinstance(item, dict) and item.get("status") == "APPROVED_FOR_REDISTRIBUTION"
                        and isinstance(item.get("review"), dict) and item["review"].get("reviewer")
                        and item["review"].get("decision_url")
                        and isinstance(item.get("license"), dict)
                        and item["license"].get("id")
                        and re.fullmatch(r"[0-9a-f]{64}", item["license"].get("evidence_sha256", ""))
                        and isinstance(item.get("retrieval"), dict)
                        and re.fullmatch(r"[0-9a-f]{64}", item["retrieval"].get("sha256", ""))}
            source_ids = evidence.get("source_ids")
            if (not isinstance(source_ids, list) or not source_ids
                    or any(not isinstance(s, str) or not s for s in source_ids)
                    or len(source_ids) != len(set(source_ids))
                    or any(source_id not in admitted for source_id in source_ids)):
                problem(f"releaseReady requires independently admitted sources: {code}")
    if manifest is not None:
        published = manifest.get("languages", [])
        current = {x.get("code"): x for x in published if isinstance(x, dict)}
        if len(current) != len(published) or set(current) != ids:
            problem("published manifest ID mismatch; explicit versioned migration required")
        for lang in languages:
            old = current.get(lang.get("id"))
            if old is None:
                continue
            if old.get("family") != lang.get("family"):
                problem(f"inconsistent family versus published manifest: {lang['id']}")
            if old.get("native_name") != lang.get("native_name"):
                problem(f"changed native name versus published manifest: {lang['id']}")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=HERE / "language_registry.v1.json")
    parser.add_argument("--readiness", type=Path, default=HERE / "content_readiness.v1.json")
    parser.add_argument("--manifest", type=Path, default=HERE.parent / "manifest.json")
    args = parser.parse_args(argv)
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    readiness = json.loads(args.readiness.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    ledger = json.loads((HERE.parent / "legal" / "ledger" / "sources.json").read_text(encoding="utf-8"))
    failures = validate(registry, readiness, manifest, source_ledger=ledger)
    for failure in failures:
        print("ERROR:", failure)
    if failures:
        return 1
    print(f"OK: {len(registry['languages'])} canonical languages; {len(registry['aliases'])} compatibility aliases; "
          f"{len(registry['locale_variants'])} locale variants; readiness promotion guarded by published pack and admitted source evidence")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
