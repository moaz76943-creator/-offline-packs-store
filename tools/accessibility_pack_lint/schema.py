from typing import TypedDict, List, Optional, Union

class LabelMetadata(TypedDict, total=False):
    language: str
    script: str
    text: str
    direction: str  # "ltr" or "rtl"
    related_concept_id: str
    verified: bool

class ContrastMetadata(TypedDict, total=False):
    supported: bool
    ratio: Optional[float]
    palettes: Optional[List[str]]

class VectorBounds(TypedDict, total=False):
    max_x: float
    max_y: float

class VectorMetadata(TypedDict, total=False):
    bounds: VectorBounds
    complexity: int
    path_count: Optional[int]

class VisualAssetMetadata(TypedDict, total=False):
    id: str
    concept_id: str
    version: str
    hash: str
    provenance: str
    labels: List[LabelMetadata]
    fallback_label: str
    contrast: ContrastMetadata
    vector: VectorMetadata
    device_shaping_evidence: bool
    changed: Optional[bool]
