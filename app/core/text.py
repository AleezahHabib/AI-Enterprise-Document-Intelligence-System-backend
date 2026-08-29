"""Text normalization utilities.
Governing spec: BE-04-R23, BE-10 §5 (BE-10-R8, BE-10-R9).
Single source of truth for text normalization across extraction, chunking, and quote verification.
"""

import re
import unicodedata


def normalize(text: str) -> str:
    """Normalize Unicode, quotes, dashes, and soft hyphens (BE-04-R23, BE-10-R8)."""
    if not text:
        return ""

    # NFKC Unicode normalization
    s = unicodedata.normalize("NFKC", text)

    # Replace smart/curly quotes with standard ASCII quotes
    s = re.sub(r"[\u2018\u2019\u201A\u201B\u2032\u2035]", "'", s)
    s = re.sub(r"[\u201C\u201D\u201E\u201F\u2033\u2036]", '"', s)

    # Replace em-dashes, en-dashes, and horizontal bars with standard hyphen
    s = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]", "-", s)

    # Remove soft hyphens and zero-width spaces
    s = re.sub(r"[\u00AD\u200B\u200C\u200D\uFEFF]", "", s)

    # Replace non-breaking spaces and irregular whitespace controls with space
    s = re.sub(r"[\u00A0\u1680\u2000-\u200A\u202F\u205F\u3000\t\r\f\v]+", " ", s)

    return s


def normalize_for_match(text: str) -> str:
    """Normalize text specifically for deterministic quote substring matching (BE-10-R8).
    
    1. Base normalize (NFKC, quotes, dashes, de-hyphenation)
    2. Collapse all whitespace to single spaces
    3. Casefold (case-insensitive)
    """
    s = normalize(text)
    s = re.sub(r"\s+", " ", s)
    return s.strip().casefold()
