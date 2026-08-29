"""Structure-aware token chunking service using LlamaIndex chunking utilities.
Governing spec: BE-05, ADR-0009, ADR-0010.
"""

import re
from typing import List, Optional, Tuple
import tiktoken
from llama_index.core.node_parser import SentenceSplitter

from app.core.config import Settings
from app.core.errors import NoContentAfterChunkingError
from app.models.extraction import ExtractedBlock, ExtractedDocument
from app.models.chunking import PreparedChunk

# Pre-compiled sentence splitter regex per BE-05-R9
SENTENCE_SPLIT_REGEX = re.compile(r"([.!?])\s+([A-Z0-9])")
ABBREVIATIONS = {
    "inc.", "ltd.", "no.", "e.g.", "i.e.", "art.", "sec.", "cf.", "vs.", "etc.",
    "mr.", "mrs.", "ms.", "dr.", "prof.", "dept.", "approx.", "est."
}


def count_tokens(text: str, encoder: tiktoken.Encoding) -> int:
    """Measure token count using tiktoken (cl100k_base)."""
    return len(encoder.encode(text, disallowed_special=()))


def split_into_sentences(text: str) -> List[str]:
    """Split text into sentences using LlamaIndex SentenceSplitter with abbreviations support."""
    if not text or not text.strip():
        return []

    try:
        splitter = SentenceSplitter(chunk_size=1024, chunk_overlap=0)
        llama_splits = splitter.split_text(text)
        if llama_splits and len(llama_splits) > 1:
            return llama_splits
    except Exception:
        pass

    splits = []
    last_idx = 0
    
    for match in SENTENCE_SPLIT_REGEX.finditer(text):
        punc_idx = match.start(1)
        next_char_idx = match.start(2)
        
        prefix = text[max(0, punc_idx - 10):punc_idx + 1].strip().lower()
        word = prefix.split()[-1] if prefix.split() else ""
        
        is_digit_period = (
            punc_idx > 0 and text[punc_idx - 1].isdigit() and
            punc_idx + 1 < len(text) and text[punc_idx + 1].isdigit()
        )
        
        if word in ABBREVIATIONS or is_digit_period:
            continue
            
        sentence = text[last_idx:match.start() + 1].strip()
        if sentence:
            splits.append(sentence)
        last_idx = next_char_idx

    tail = text[last_idx:].strip()
    if tail:
        splits.append(tail)

    return splits or [text]


def format_section_path(heading_stack: List[str]) -> Optional[str]:
    """Format and cap section hierarchy (BE-05-R10, BE-05-R11)."""
    if not heading_stack:
        return None
    full_path = " > ".join(heading_stack)
    if len(full_path) <= 200:
        return full_path
    return "…" + full_path[-(199):]


def chunk_document(doc: ExtractedDocument, settings: Settings) -> List[PreparedChunk]:
    """Structure-aware chunking over ExtractedDocument blocks with LlamaIndex token utilities."""
    encoder = tiktoken.get_encoding("cl100k_base")
    raw_chunks: List[dict] = []
    heading_stack: List[Tuple[int, str]] = []  # [(level, text)]

    current_sentences: List[str] = []
    current_tokens = 0
    current_page_from: Optional[int] = None
    current_page_to: Optional[int] = None
    current_char_start: Optional[int] = None
    current_char_end: Optional[int] = None

    def flush_chunk():
        nonlocal current_sentences, current_tokens, current_page_from, current_page_to, current_char_start, current_char_end
        if not current_sentences:
            return
        chunk_text = " ".join(current_sentences).strip()
        if len(chunk_text) >= settings.MIN_CHARS_PER_CHUNK:
            current_section_path = format_section_path([h[1] for h in heading_stack])
            raw_chunks.append({
                "content": chunk_text,
                "token_count": count_tokens(chunk_text, encoder),
                "page_from": current_page_from,
                "page_to": current_page_to,
                "char_start": current_char_start or 0,
                "char_end": current_char_end or len(chunk_text),
                "section_path": current_section_path,
            })
        current_sentences = []
        current_tokens = 0
        current_page_from = None
        current_page_to = None
        current_char_start = None
        current_char_end = None

    for block in doc.blocks:
        # Heading boundary triggers immediate flush
        if block.heading_level is not None:
            flush_chunk()
            level = block.heading_level
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, block.text.strip()))
            continue

        sentences = split_into_sentences(block.text)
        for sent in sentences:
            sent_tokens = count_tokens(sent, encoder)
            
            if current_tokens + sent_tokens > settings.CHUNK_TARGET_TOKENS and current_sentences:
                flush_chunk()

            if not current_sentences:
                current_char_start = block.char_start
                current_page_from = block.page

            current_sentences.append(sent)
            current_tokens += sent_tokens
            current_page_to = block.page or current_page_to
            current_char_end = block.char_end

            if current_tokens >= settings.CHUNK_TARGET_TOKENS:
                flush_chunk()

    # Flush any remainder
    flush_chunk()

    if not raw_chunks:
        raise NoContentAfterChunkingError()

    # Merge trailing small chunk into previous chunk if below CHUNK_MIN_TOKENS
    if len(raw_chunks) > 1 and raw_chunks[-1]["token_count"] < settings.CHUNK_MIN_TOKENS:
        last = raw_chunks.pop()
        prev = raw_chunks[-1]
        merged_content = prev["content"] + "\n\n" + last["content"]
        merged_tokens = count_tokens(merged_content, encoder)
        if merged_tokens <= settings.CHUNK_MAX_TOKENS:
            raw_chunks[-1]["content"] = merged_content
            raw_chunks[-1]["token_count"] = merged_tokens
            raw_chunks[-1]["char_end"] = last["char_end"]
            raw_chunks[-1]["page_to"] = last["page_to"] or prev["page_to"]
        else:
            raw_chunks.append(last)

    # Build PreparedChunk instances with strict separation
    prepared_chunks: List[PreparedChunk] = []
    for ordinal, c in enumerate(raw_chunks):
        content = c["content"]
        section_path = c["section_path"]
        
        if section_path:
            embedding_input = f"{section_path}\n\n{content}"
        else:
            embedding_input = content

        prepared_chunks.append(
            PreparedChunk(
                ordinal=ordinal,
                content=content,
                embedding_input=embedding_input,
                token_count=c["token_count"],
                char_start=c["char_start"],
                char_end=c["char_end"],
                page_from=c["page_from"],
                page_to=c["page_to"],
                section_path=section_path,
            )
        )

    return prepared_chunks
