import json
from pathlib import Path
import jsonschema

BASE = Path(__file__).resolve().parent

class MorphologyValidator:
    def __init__(self):
        with open(BASE / 'form.schema.json', 'r', encoding='utf-8') as f:
            self.schema = json.load(f)
        with open(BASE / 'feature_overrides.json', 'r', encoding='utf-8') as f:
            self.overrides = json.load(f)

        # Build strict compatibility map
        self.compatibility = self.overrides.get('overrides', {})
        self.default_features = self.overrides.get('features', [])

    def _is_applicable(self, language, feature):
        if language in self.compatibility and feature in self.compatibility[language]:
            return self.compatibility[language][feature] != 'not_applicable'
        return True # if unknown or unlisted, it's considered valid unless explicitly not_applicable

    def validate(self, form_record):
        # 1. Schema Validation
        try:
            jsonschema.validate(instance=form_record, schema=self.schema)
        except jsonschema.exceptions.ValidationError as e:
            raise ValueError(f"Schema validation failed: {e.message}")

        lang = form_record['language_code']

        # 2. Lemma and Sense Reference Verification
        if not form_record['lemma_id'].startswith(f"{lang}:"):
            raise ValueError(f"lemma_id '{form_record['lemma_id']}' must start with language_code '{lang}:'")
        if not form_record['sense_id'].startswith(f"{lang}:"):
            raise ValueError(f"sense_id '{form_record['sense_id']}' must start with language_code '{lang}:'")

        # 4. Property Mapping Checks (outer properties)
        prop_feature_map_outer = {
            'orthographic_variant': 'orthographic_variants',
        }
        for prop, feat in prop_feature_map_outer.items():
            if prop in form_record:
                if not self._is_applicable(lang, feat):
                    raise ValueError(f"Property '{prop}' requires feature '{feat}' which is not applicable for '{lang}'")

        # 3. Analyze each analysis for features and inner properties
        analyses = form_record.get('analyses', [])
        for analysis in analyses:
            features = analysis.get('features', {})
            for feature, value in features.items():
                if not self._is_applicable(lang, feature):
                    raise ValueError(f"Feature '{feature}' is explicitly not applicable for language '{lang}'")

            prop_feature_map_inner = {
                'root': 'root_pattern',
                'pattern': 'root_pattern',
                'vowel_harmony_class': 'vowel_harmony',
                'segmentation': 'segmentation',
            }
            for prop, feat in prop_feature_map_inner.items():
                if prop in analysis:
                    if not self._is_applicable(lang, feat):
                        raise ValueError(f"Property '{prop}' requires feature '{feat}' which is not applicable for '{lang}'")

            # Check nonconcatenative fallback for root/pattern
            if 'root' in analysis or 'pattern' in analysis:
                 if not self._is_applicable(lang, 'root_pattern') and not self._is_applicable(lang, 'nonconcatenative'):
                     raise ValueError(f"root/pattern requires root_pattern or nonconcatenative features which are not applicable for '{lang}'")

            # 5. Process Mapping Checks
            processes = analysis.get('processes', [])
            for process in processes:
                # Try matching process name to feature exactly
                if process in self.default_features:
                     if not self._is_applicable(lang, process):
                         raise ValueError(f"Process '{process}' is explicitly not applicable for language '{lang}'")
                # Special case compound
                if 'compound' in process and not self._is_applicable(lang, 'compound'):
                     raise ValueError(f"Process '{process}' requires 'compound' feature which is not applicable for '{lang}'")
                # Special case broken_plural -> nonconcatenative
                if process == 'broken_plural' and not self._is_applicable(lang, 'nonconcatenative') and not self._is_applicable(lang, 'root_pattern'):
                     raise ValueError(f"Process 'broken_plural' requires 'nonconcatenative' or 'root_pattern' feature not applicable for '{lang}'")

            # 6. Morpheme Mapping Checks
            morphemes = analysis.get('morphemes', [])
            morpheme_feature_map = {
                'prefix': 'prefix',
                'suffix': 'suffix',
                'clitic': 'clitic',
                'compound_member': 'compound',
                'root': 'root_pattern',
                'pattern': 'root_pattern'
            }
            for morpheme in morphemes:
                kind = morpheme.get('kind')
                if kind in morpheme_feature_map:
                    feat = morpheme_feature_map[kind]
                    if not self._is_applicable(lang, feat):
                         # fallback nonconcatenative for root/pattern
                         if kind in ['root', 'pattern'] and self._is_applicable(lang, 'nonconcatenative'):
                             continue
                         raise ValueError(f"Morpheme kind '{kind}' requires feature '{feat}' which is not applicable for '{lang}'")

        return True
