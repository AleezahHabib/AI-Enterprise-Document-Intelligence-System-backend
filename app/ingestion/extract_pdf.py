"""PDF text extraction using PyMuPDF.
Governing spec: BE-04, ADR-0008.
Preserves page numbers, bounding boxes, and heading structure.
"""

import io
import re
from collections import Counter
from typing import List, Optional, Tuple
import fitz  # PyMuPDF

from app.core.config import Settings
from app.core.errors import (
    DocumentEncryptedError,
    DocumentCorruptError,
    DocumentTooLongError,
    NoTextExtractedError,
)
from app.models.extraction import ExtractedBlock, ExtractedDocument


def _normalize_header_text(text: str) -> str:
    """Normalize text for header/footer comparison (digits to #)."""
    text = re.sub(r"\d+", "#", text.strip())
    return re.sub(r"\s+", " ", text).lower()


def extract_pdf(pdf_bytes: bytes, filename: str, settings: Settings) -> ExtractedDocument:
    """Extract structured text from a PDF file."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise DocumentCorruptError()

    # BE-04-R12: Encrypted PDF check
    if doc.is_encrypted:
        if not doc.authenticate(""):
            doc.close()
            raise DocumentEncryptedError()

    # BE-04-R14: MAX_PAGES check
    page_count = len(doc)
    if page_count > settings.MAX_PAGES:
        doc.close()
        raise DocumentTooLongError()

    if page_count == 0:
        doc.close()
        raise NoTextExtractedError()

    # Step 1: Extract all lines and spans across all pages
    page_lines: List[List[dict]] = []
    font_sizes: List[float] = []
    total_extracted_chars = 0

    for page_idx in range(page_count):
        page = doc[page_idx]
        page_dict = page.get_text("dict")
        lines_on_page = []
        page_rect = page.rect
        page_height = page_rect.height

        for block in page_dict.get("blocks", []):
            if block.get("type") == 0:  # text block
                for line in block.get("lines", []):
                    line_text = ""
                    line_font_sizes = []
                    is_bold = False
                    bbox = line.get("bbox", (0, 0, 0, 0))

                    for span in line.get("spans", []):
                        span_text = span.get("text", "")
                        line_text += span_text
                        sz = span.get("size", 0)
                        if sz > 0:
                            line_font_sizes.append(sz)
                            font_sizes.append(round(sz, 1))
                        flags = span.get("flags", 0)
                        if flags & 2 or "bold" in span.get("font", "").lower():
                            is_bold = True

                    line_text_clean = re.sub(r"[\u00A0\t\r\f\v ]+", " ", line_text).strip()
                    if line_text_clean:
                        avg_sz = sum(line_font_sizes) / len(line_font_sizes) if line_font_sizes else 10.0
                        lines_on_page.append({
                            "text": line_text_clean,
                            "bbox": bbox,
                            "page": page_idx + 1,
                            "y0": bbox[1],
                            "y1": bbox[3],
                            "x0": bbox[0],
                            "x1": bbox[2],
                            "rel_top": bbox[1] / max(page_height, 1.0),
                            "rel_bottom": (page_height - bbox[3]) / max(page_height, 1.0),
                            "font_size": avg_sz,
                            "is_bold": is_bold,
                        })
                        total_extracted_chars += len(line_text_clean)

        page_lines.append(lines_on_page)

    # BE-04-R6: Scanned PDF detection (< MIN_CHARS_PER_PAGE)
    if (total_extracted_chars / page_count) < settings.MIN_CHARS_PER_PAGE:
        doc.close()
        raise NoTextExtractedError()

    # Step 2: Modal body font size for heading detection
    modal_font_size = 11.0
    if font_sizes:
        modal_font_size = Counter(font_sizes).most_common(1)[0][0]

    # Step 3: BE-04-R8 Header and footer detection (top/bottom 8% occurring on >50% pages when page_count > 1)
    suppressed_headers = set()
    suppressed_footers = set()

    if page_count > 1:
        header_counts: Counter[str] = Counter()
        footer_counts: Counter[str] = Counter()

        for lines in page_lines:
            for line in lines:
                norm = _normalize_header_text(line["text"])
                if line["rel_top"] <= 0.08:
                    header_counts[norm] += 1
                if line["rel_bottom"] <= 0.08:
                    footer_counts[norm] += 1

        suppressed_headers = {norm for norm, count in header_counts.items() if (count / page_count) > 0.5}
        suppressed_footers = {norm for norm, count in footer_counts.items() if (count / page_count) > 0.5}


    # Step 4: Assemble blocks and canonical plain text
    extracted_blocks: List[ExtractedBlock] = []
    canonical_text_parts: List[str] = []
    current_char_offset = 0

    numbered_heading_pattern = re.compile(r"^(\d+(\.\d+)*)\s+\S")

    for page_idx, lines in enumerate(page_lines):
        # BE-04-R5: Two-column sorting by column band then y0 then x0
        lines.sort(key=lambda l: (round(l["x0"] / 250.0), l["y0"], l["x0"]))

        for line in lines:
            norm = _normalize_header_text(line["text"])
            if (line["rel_top"] <= 0.08 and norm in suppressed_headers) or \
               (line["rel_bottom"] <= 0.08 and norm in suppressed_footers):
                continue

            text = line["text"]
            # BE-04-R9: Heading detection
            heading_level: Optional[int] = None
            is_large_font = line["font_size"] >= (1.15 * modal_font_size) and len(text) <= 120
            is_bold_short = line["is_bold"] and len(text) <= 80
            numbered_match = numbered_heading_pattern.match(text)

            if numbered_match:
                clause_num = numbered_match.group(1)
                heading_level = min(6, clause_num.count(".") + 1)
            elif is_large_font:
                ratio = line["font_size"] / max(modal_font_size, 1.0)
                if ratio >= 1.5:
                    heading_level = 1
                elif ratio >= 1.3:
                    heading_level = 2
                else:
                    heading_level = 3
            elif is_bold_short:
                heading_level = 3

            # Append separator if needed
            if canonical_text_parts:
                canonical_text_parts.append("\n\n")
                current_char_offset += 2

            block_start = current_char_offset
            canonical_text_parts.append(text)
            current_char_offset += len(text)
            block_end = current_char_offset

            extracted_blocks.append(
                ExtractedBlock(
                    text=text,
                    page=line["page"],
                    char_start=block_start,
                    char_end=block_end,
                    heading_level=heading_level,
                    bbox=line["bbox"],
                )
            )

    full_canonical_text = "".join(canonical_text_parts)

    # Document title extraction (BE-04-R11)
    doc_title = None
    if doc.metadata and doc.metadata.get("title"):
        meta_title = doc.metadata["title"].strip()
        if meta_title and not meta_title.lower().endswith((".pdf", ".docx")):
            doc_title = meta_title

    if not doc_title:
        for block in extracted_blocks:
            if block.heading_level == 1:
                doc_title = block.text.strip()
                break

    if not doc_title:
        doc_title = filename.rsplit(".", 1)[0]

    doc_title = re.sub(r"\s+", " ", doc_title).strip()
    doc.close()

    return ExtractedDocument(
        text=full_canonical_text,
        blocks=extracted_blocks,
        page_count=page_count,
        title=doc_title,
    )
