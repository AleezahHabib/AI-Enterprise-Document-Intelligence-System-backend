"""Extraction output domain models.
Governing spec: BE-04 §3.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class ExtractedBlock:
    text: str
    page: Optional[int]                 # 1-indexed; None for DOCX
    char_start: int                     # offset into ExtractedDocument.text
    char_end: int                       # offset into ExtractedDocument.text
    heading_level: Optional[int]        # 1-6 if heading, else None
    bbox: Optional[Tuple[float, float, float, float]]  # PDF only (x0, y0, x1, y1) in user-space


@dataclass(frozen=True)
class ExtractedDocument:
    text: str                           # Canonical plain text reference
    blocks: List[ExtractedBlock]
    page_count: Optional[int]
    title: Optional[str]
