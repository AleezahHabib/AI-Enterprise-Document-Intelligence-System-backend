"""Unit tests for BE-16 Golden Evaluation Set schema and composition.
Named by requirement IDs per BE-16-R4.
"""

import json
from pathlib import Path
import pytest


def load_golden_set():
    golden_set_path = Path(__file__).parent.parent.parent / "eval" / "golden_set.jsonl"
    assert golden_set_path.exists(), f"Golden set file not found at {golden_set_path}"
    
    entries = []
    with open(golden_set_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def test_be_16_r7_golden_set_has_at_least_100_entries():
    """BE-16-R7: Golden set contains >= 100 questions over the demo corpus."""
    entries = load_golden_set()
    assert len(entries) >= 100, f"Expected >= 100 entries, found {len(entries)}"


def test_be_16_r8_golden_set_unanswerable_ratio_at_least_30_percent():
    """BE-16-R8: At least 30% of entries MUST be answerable: false."""
    entries = load_golden_set()
    unanswerable = [e for e in entries if not e.get("answerable", True)]
    ratio = len(unanswerable) / len(entries)
    assert ratio >= 0.30, f"Unanswerable ratio {ratio:.2%} is below 30% threshold"


def test_be_16_r9_golden_set_covers_four_negative_categories():
    """BE-16-R9: Unanswerable questions cover all four required categories."""
    entries = load_golden_set()
    unanswerable = [e for e in entries if not e.get("answerable", True)]
    
    categories = {e.get("category") for e in unanswerable}
    required_categories = {
        "unanswerable_adjacent_topic",
        "unanswerable_plausible_absent",
        "unanswerable_right_doc_wrong_fact",
        "unanswerable_off_corpus",
    }
    
    missing = required_categories - categories
    assert not missing, f"Golden set missing negative categories: {missing}"
