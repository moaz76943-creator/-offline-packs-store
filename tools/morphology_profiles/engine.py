"""Conservative, evidence-backed morphology capabilities and attested-form lookup.

No paradigms are inferred from surface strings. Unknown data stays unknown.
Only Python standard library is required, and lookup memory is bounded.
"""
from collections import OrderedDict
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STANDARDS = ROOT / "standards" / "morphology"
UNKNOWN = "unknown"
STATUSES = frozenset(("supported", "not_applicable", UNKNOWN))


class ContractError(ValueError):
    """Invalid or inconsistent public morphology evidence."""


def _json(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


class MorphologyEngine:
    """Lazy O(N) registry index, bounded LRU profiles and lexical form cache."""

    def __init__(self, registry_path=None, standards_path=None, cache_size=32):
        if not isinstance(cache_size, int) or not 1 <= cache_size <= 128:
            raise ContractError("cache_size must be in 1..128")
        self.standards = Path(standards_path or STANDARDS)
        self.registry_path = Path(registry_path or os.environ.get("MORPHOLOGY_REGISTRY", ROOT / "manifest.json"))
        self.rules = _json(self.standards / "feature_overrides.json")
        self.sources = _json(self.standards / "sources.json")["sources"]
        self.features = tuple(self.rules["features"])
        if len(set(self.features)) != len(self.features):
            raise ContractError("duplicate feature names")
        self._validate_rulebook()
        manifest = _json(self.registry_path)
        languages = manifest.get("languages")
        if not isinstance(languages, list) or len(languages) != 100:
            raise ContractError("registry must contain exactly 100 registered languages")
        self._languages = {}
        for item in languages:
            code = item.get("code")
            if not isinstance(code, str) or not code or code in self._languages:
                raise ContractError("invalid or duplicate registry language code")
            self._languages[code] = {
                "code": code,
                "family": item.get("family") or UNKNOWN,
                "name": item.get("name") or UNKNOWN,
                "native_name": item.get("native_name") or UNKNOWN,
                "registry_direction": item.get("direction") or UNKNOWN,
            }
        if not set(self.rules["overrides"]).issubset(self._languages):
            raise ContractError("override references unregistered language")
        if not set(self.rules["pilot_languages"]).issubset(self._languages):
            raise ContractError("missing pilot language")
        self.cache_size = cache_size
        self._profile_cache = OrderedDict()
        self._forms_cache = OrderedDict()

    def _validate_rulebook(self):
        feature_set = set(self.features)
        for code, values in self.rules["overrides"].items():
            if not set(values).issubset(feature_set):
                raise ContractError(f"unknown feature in {code} override")
            if any(status not in STATUSES for status in values.values()):
                raise ContractError(f"invalid capability status for {code}")
        for key, contract in self.rules["contracts"].items():
            if not set(contract["features"]).issubset(feature_set):
                raise ContractError(f"unknown contract feature: {key}")
            for code in contract["languages"]:
                overrides = self.rules["overrides"].get(code, {})
                if any(overrides.get(feature) != "supported" for feature in contract["features"]):
                    raise ContractError(f"contract not declared explicitly: {key}/{code}")

    @property
    def language_codes(self):
        return tuple(self._languages)

    def profile(self, language_code):
        """Retrieve one profile without producing full paradigms or copying 100 profiles."""
        if language_code not in self._languages:
            raise KeyError(f"unregistered language: {language_code}")
        if language_code in self._profile_cache:
            self._profile_cache.move_to_end(language_code)
            return self._profile_cache[language_code]
        identity = dict(self._languages[language_code])
        feature_statuses = dict.fromkeys(self.features, UNKNOWN)
        feature_statuses.update(self.rules["overrides"].get(language_code, {}))
        result = {
            "schema_version": self.rules["schema_version"],
            "identity": identity,
            "scripts": list(self.rules["scripts"].get(language_code, [])),
            "capabilities": feature_statuses,
            "analysis_status": "pilot_attested" if language_code in self.rules["pilot_languages"] else "capability_only",
            "form_inventory_complete": False,
        }
        self._store(self._profile_cache, language_code, result)
        return result

    def iter_profiles(self):
        for code in self.language_codes:
            yield self.profile(code)

    def contracts(self, language_code):
        self.profile(language_code)  # validates identity
        return {name: contract for name, contract in self.rules["contracts"].items()
                if language_code in contract["languages"]}

    def _store(self, cache, key, value):
        cache[key] = value
        if len(cache) > self.cache_size:
            cache.popitem(last=False)

    def _load_lemma(self, language_code, lemma_id):
        key = (language_code, lemma_id)
        if key in self._forms_cache:
            self._forms_cache.move_to_end(key)
            return self._forms_cache[key]
        forms = []
        # Sequential JSONL scan is deliberate: avoids a growing all-language index.
        with (self.standards / "attested_forms.jsonl").open(encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("language_code") == language_code and record.get("lemma_id") == lemma_id:
                    if len(forms) >= 128:
                        raise ContractError("too many forms for one lemma")
                    if record.get("source_id") not in self.sources:
                        raise ContractError(f"missing source for form at line {line_no}")
                    if not record.get("sense_id") or not record.get("evidence_version"):
                        raise ContractError(f"missing evidence identifiers at line {line_no}")
                    tags = record.get("features", {})
                    if not isinstance(tags, dict):
                        raise ContractError("invalid form features")
                    for name in tags:
                        if name not in self.features and name != "verb_form":
                            raise ContractError(f"unrecognized form feature {name}")
                        if name in self.features and self.profile(language_code)["capabilities"][name] != "supported":
                            raise ContractError(f"form tagged with unlicensed capability: {language_code}/{name}")
                    forms.append(record)
        self._store(self._forms_cache, key, tuple(forms))
        return self._forms_cache[key]

    def analyze(self, language_code, lemma_id, features=None, sense_id=None):
        """Return attestations matching all exact tags, or UNKNOWN, never guesses."""
        profile = self.profile(language_code)
        if not isinstance(lemma_id, str) or not lemma_id.startswith(language_code + ":"):
            raise ContractError("lemma identifier must be language-scoped")
        features = {} if features is None else features
        if not isinstance(features, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                                    for k, v in features.items()):
            raise ContractError("features must map strings to strings")
        if not set(features).issubset(set(self.features) | {"verb_form"}):
            raise ContractError("unknown feature key")
        if any(profile["capabilities"][key] != "supported" for key in features if key in self.features):
            return {"status": UNKNOWN, "forms": [], "reason": "unsupported_or_unverified_feature"}
        records = [record for record in self._load_lemma(language_code, lemma_id)
                   if (sense_id is None or record["sense_id"] == sense_id)
                   and all(record["features"].get(k) == v for k, v in features.items())]
        return {"status": "attested" if records else UNKNOWN, "forms": records}

    @property
    def cache_usage(self):
        return {"profiles": len(self._profile_cache), "lemmas": len(self._forms_cache)}


def main():
    """Summarize capability coverage without materializing all inflections."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", help="Path to read-only public language manifest")
    parser.add_argument("--language", help="Return one language capability profile")
    args = parser.parse_args()
    engine = MorphologyEngine(registry_path=args.registry)
    if args.language:
        print(json.dumps(engine.profile(args.language), ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"registered": len(engine.language_codes),
                          "attested_pilots": engine.rules["pilot_languages"],
                          "capability_only": len(engine.language_codes) - len(engine.rules["pilot_languages"])}))


if __name__ == "__main__":
    main()
