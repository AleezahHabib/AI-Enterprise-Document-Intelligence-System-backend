"""DOCX text extraction using python-docx.
Governing spec: BE-04 §5.
Extracts headings, paragraphs, and markdown tables; ignores tracked deletions.
"""

import io
import re
from typing import List, Optional
import docx

from app.core.config import Settings
from app.core.errors import DocumentCorruptError, NoTextExtractedError
from app.models.extraction import ExtractedBlock, ExtractedDocument


def _table_to_markdown(table) -> str:
    """Convert a DOCX table into a markdown table string (BE-04-R17)."""
    rows_data: List[List[str]] = []
    for row in table.rows:
        row_cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
        rows_data.append(row_cells)

    if not rows_data:
        return ""

    num_cols = max(len(r) for r in rows_data)
    md_lines = []
    
    # Header row
    header = rows_data[0] + [""] * (num_cols - len(rows_data[0]))
    md_lines.append("| " + " | ".join(header) + " |")
    md_lines.append("| " + " | ".join(["---"] * num_cols) + " |")

    # Data rows
    for r in rows_data[1:]:
        row_padded = r + [""] * (num_cols - len(r))
        md_lines.append("| " + " | ".join(row_padded) + " |")

    return "\n".join(md_lines)


def extract_docx(docx_bytes: bytes, filename: str, settings: Settings) -> ExtractedDocument:
    """Extract structured text from a DOCX file."""
    try:
        doc = docx.Document(io.BytesIO(docx_bytes))
    except Exception as e:
        raise DocumentCorruptError()

    extracted_blocks: List[ExtractedBlock] = []
    canonical_text_parts: List[str] = []
    current_char_offset = 0
    doc_title: Optional[str] = None

    numbered_heading_pattern = re.compile(r"^(\d+(\.\d+)*)\s+\S")

    # Iterate through body elements (paragraphs and tables)
    for element in doc.element.body:
        tag_name = element.tag.split("}")[-1] if "}" in element.tag else element.tag

        if tag_name == "p":
            para = docx.text.paragraph.Paragraph(element, doc)
            # BE-04-R18: Filter out tracked deletions (<w:del> tags in XML)
            text = para.text.strip()
            if not text:
                continue

            style_name = para.style.name.lower() if para.style else ""
            heading_level: Optional[int] = None

            if "heading 1" in style_name or "title" in style_name:
                heading_level = 1
                if not doc_title and "title" in style_name:
                    doc_title = text
            elif "heading 2" in style_name:
                heading_level = 2
            elif "heading 3" in style_name:
                heading_level = 3
            elif "heading 4" in style_name:
                heading_level = 4
            elif "heading 5" in style_name:
                heading_level = 5
            elif "heading 6" in style_name:
                heading_level = 6
            else:
                num_match = numbered_heading_pattern.match(text)
                if num_match:
                    clause_num = num_match.group(1)
                    heading_level = min(6, clause_num.count(".") + 1)

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
                    page=None,
                    char_start=block_start,
                    char_end=block_end,
                    heading_level=heading_level,
                    bbox=None,
                )
            )

        elif tag_name == "tbl":
            tbl = docx.table.Table(element, doc)
            table_md = _table_to_markdown(tbl)
            if not table_md:
                continue

            if canonical_text_parts:
                canonical_text_parts.append("\n\n")
                current_char_offset += 2

            block_start = current_char_offset
            canonical_text_parts.append(table_md)
            current_char_offset += len(table_md)
            block_end = current_char_offset

            extracted_blocks.append(
                ExtractedBlock(
                    text=table_md,
                    page=None,
                    char_start=block_start,
                    char_end=block_end,
                    heading_level=None,
                    bbox=None,
                )
            )

    full_canonical_text = "".join(canonical_text_parts)

    if not full_canonical_text.strip():
        raise NoTextExtractedError()

    if not doc_title:
        for block in extracted_blocks:
            if block.heading_level == 1:
                doc_title = block.text.strip()
                break

    if not doc_title:
        doc_title = filename.rsplit(".", 1)[0]

    return ExtractedDocument(
        text=full_canonical_text,
        blocks=extracted_blocks,
        page_count=None,
        title=doc_title,
    )
