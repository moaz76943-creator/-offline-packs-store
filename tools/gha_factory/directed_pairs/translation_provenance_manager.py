#!/usr/bin/env python3
"""
Directed Translation Provenance Manager.
Master Constitution Section 02 & 08 Compliant.
Guarantees directed pair asymmetry (A->B != B->A) and tracks
immutable source provenance, license attribution, and confidence score.
"""
import json
import sys

PROVENANCE_DIRECT = "DIRECT_ATTESTED"
PROVENANCE_PIVOT = "PIVOT_INFERRED"

class DirectedTranslationEdge:
    def __init__(self, source_lang: str, target_lang: str, source_lemma: str,
                 target_lemma: str, source_id: str, license_id: str,
                 provenance_type: str = PROVENANCE_DIRECT, confidence: float = 1.0):
        self.source_lang = source_lang.lower().strip()
        self.target_lang = target_lang.lower().strip()
        self.source_lemma = source_lemma.strip()
        self.target_lemma = target_lemma.strip()
        self.source_id = source_id.strip()
        self.license_id = license_id.strip()
        self.provenance_type = provenance_type
        self.confidence = float(confidence)

    def to_dict(self):
        return {
            'directed_pair': f"{self.source_lang}->{self.target_lang}",
            'source_lang': self.source_lang,
            'target_lang': self.target_lang,
            'source_lemma': self.source_lemma,
            'target_lemma': self.target_lemma,
            'provenance_type': self.provenance_type,
            'source_id': self.source_id,
            'license_id': self.license_id,
            'confidence': self.confidence,
        }

class DirectedTranslationStore:
    def __init__(self):
        # Keyed strictly by directed pair string: e.g. "de->ar"
        self._edges = {}

    def add_edge(self, edge: DirectedTranslationEdge):
        if not edge.source_id or not edge.license_id:
            raise ValueError(f"CRITICAL: Missing legal provenance for translation {edge.source_lemma} -> {edge.target_lemma}")
        
        pair_key = f"{edge.source_lang}->{edge.target_lang}"
        if pair_key not in self._edges:
            self._edges[pair_key] = []
        self._edges[pair_key].append(edge)

    def get_translations(self, source_lang: str, target_lang: str, source_lemma: str):
        pair_key = f"{source_lang.lower()}->{target_lang.lower()}"
        candidates = self._edges.get(pair_key, [])
        return [e for e in candidates if e.source_lemma == source_lemma]

    def has_reverse_edge(self, edge: DirectedTranslationEdge) -> bool:
        """Verifies if the reverse direction is independently attested (A->B != B->A rule)."""
        reverse_key = f"{edge.target_lang}->{edge.source_lang}"
        reverse_candidates = self._edges.get(reverse_key, [])
        return any(e.source_lemma == edge.target_lemma and e.target_lemma == edge.source_lemma for e in reverse_candidates)
