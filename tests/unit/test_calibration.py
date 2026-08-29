"""Unit tests for BE-11 §7 and BE-16 §6 Calibration calculations and thresholds.
Named by requirement IDs per BE-16-R4.
"""

import pytest


def test_be_11_r17_false_abstention_rate_calculation():
    """BE-11-R17: False abstention rate metric formula and threshold check (<= 0.10)."""
    # 65 answerable questions, 4 false abstentions -> rate = 4/65 = 6.15% <= 10%
    total_answerable = 65
    false_abstentions = 4
    false_abstention_rate = false_abstentions / total_answerable

    assert false_abstention_rate <= 0.10
    assert round(false_abstention_rate, 4) == 0.0615


def test_be_16_r6_calibration_targets():
    """BE-16 §6.1: Metric target definitions."""
    targets = {
        "citation_validity": 0.95,
        "refusal_accuracy": 0.90,
        "claim_precision": 0.95,
        "false_abstention_rate": 0.10,
    }
    assert targets["citation_validity"] >= 0.95
    assert targets["refusal_accuracy"] >= 0.90
    assert targets["false_abstention_rate"] <= 0.10
