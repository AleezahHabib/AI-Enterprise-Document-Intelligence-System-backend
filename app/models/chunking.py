"""Chunking output domain models.
Governing spec: BE-05 §7, BE-05-R13.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PreparedChunk:
    """Represents a chunk prepared for database storage and embedding.
    
    CRITICAL DISTINCTION (BE-05-R13):
    - content: The verbatim passage text alone. Stored in DB, used for keyword search,
      grounding quotes, and LLM context.
    - embedding_input: section_path + "\\n\\n" + passage text. Used ONLY for vector generation.
    """
    ordinal: int
    content: str                        # Stored in DB (verbatim text)
    embedding_input: str                # Sent to Gemini Embedding API only
    token_count: int                    # Measured on content
    char_start: int                     # Offset in ExtractedDocument.text
    char_end: int                       # Offset in ExtractedDocument.text
    page_from: Optional[int]            # 1-indexed
    page_to: Optional[int]              # 1-indexed
    section_path: Optional[str]         # Capped at 200 chars
