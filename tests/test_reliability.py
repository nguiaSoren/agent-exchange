"""Tests for market.reliability — formula correctness, badge derivation, label.

Pins:
  - Formula 1: Z=1.96, p=0.5, E=0.05 → raw 384.16 → ceil 385.
  - Formula 1 at n=47: margin_additional = 385 - 47 = 338.
  - Formula 2: p=0.01, confidence=0.05 → raw ≈298.07 → ceil 299.
  - low_confidence boundary: True below 385, False at/above 385.
  - label strings match the documented format.
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_exchange.market.reliability import (
    ReliabilityBadge,
    formula_1_n,
    formula_2_n,
    reliability_badge,
)


# ── formula 1 ─────────────────────────────────────────────────────────────────

def test_formula_1_raw_value():
    """n = 1.96² · 0.5 · 0.5 / 0.05² = 384.16."""
    n = formula_1_n(0.5, 0.05, 1.96)
    assert abs(n - 384.16) < 0.01, f"expected ~384.16, got {n}"


def test_formula_1_ceil_is_385():
    n = formula_1_n(0.5, 0.05, 1.96)
    assert math.ceil(n) == 385


def test_formula_1_margin_required_for_47_runs():
    b = reliability_badge(47)
    assert b.margin_required == 385


def test_formula_1_margin_additional_for_47_runs():
    """At 47 runs the worker still needs 385 − 47 = 338 more jobs."""
    b = reliability_badge(47)
    assert b.margin_additional == 338


def test_formula_1_margin_additional_saturates_at_zero():
    """A worker with more runs than required shows 0 additional needed."""
    b = reliability_badge(1000)
    assert b.margin_additional == 0


def test_formula_1_margin_additional_at_exact_boundary():
    """Exactly at the required count: 0 additional needed."""
    b = reliability_badge(385)
    assert b.margin_additional == 0


# ── formula 2 ─────────────────────────────────────────────────────────────────

def test_formula_2_raw_value():
    """ln(0.05) / ln(0.99) ≈ 298.07."""
    n = formula_2_n(0.01, 0.05)
    assert abs(n - 298.07) < 0.1, f"expected ~298.07, got {n}"


def test_formula_2_ceil_is_299():
    n = formula_2_n(0.01, 0.05)
    assert math.ceil(n) == 299


def test_formula_2_rare_branch_required_is_299():
    b = reliability_badge(0)
    assert b.rare_branch_required == 299


# ── low_confidence boundary ───────────────────────────────────────────────────

def test_low_confidence_true_when_below_required():
    b = reliability_badge(47)
    assert b.low_confidence is True


def test_low_confidence_true_just_below_boundary():
    b = reliability_badge(384)
    assert b.low_confidence is True


def test_low_confidence_false_at_required():
    b = reliability_badge(385)
    assert b.low_confidence is False


def test_low_confidence_false_above_required():
    b = reliability_badge(500)
    assert b.low_confidence is False


def test_low_confidence_true_at_zero():
    b = reliability_badge(0)
    assert b.low_confidence is True


# ── label format ──────────────────────────────────────────────────────────────

def test_label_low_confidence_contains_needs():
    b = reliability_badge(47)
    assert "low confidence" in b.label
    assert "needs ~385" in b.label
    assert "±5%" in b.label
    assert "47 jobs" in b.label


def test_label_confident_format():
    b = reliability_badge(500)
    assert "500 jobs" in b.label
    assert "±5% confident" in b.label
    assert "low confidence" not in b.label


def test_label_singular_job():
    b = reliability_badge(1)
    assert "1 job ·" in b.label
    assert "low confidence" in b.label


def test_label_zero_jobs():
    b = reliability_badge(0)
    assert "0 jobs" in b.label
    assert "low confidence" in b.label


# ── badge dataclass properties ─────────────────────────────────────────────────

def test_badge_is_frozen_dataclass():
    b = reliability_badge(47)
    assert isinstance(b, ReliabilityBadge)
    try:
        b.n_jobs = 999  # type: ignore[misc]
        assert False, "should be frozen"
    except (AttributeError, TypeError):
        pass  # expected


def test_badge_fields_present():
    b = reliability_badge(212)
    assert b.n_jobs == 212
    assert isinstance(b.margin_required, int)
    assert isinstance(b.margin_additional, int)
    assert isinstance(b.rare_branch_required, int)
    assert isinstance(b.low_confidence, bool)
    assert isinstance(b.label, str)


# ── custom E parameter ─────────────────────────────────────────────────────────

def test_custom_e_tighter_margin():
    """±2.5% requires more runs than ±5%."""
    b_tight = reliability_badge(100, e=0.025)
    b_default = reliability_badge(100)
    assert b_tight.margin_required > b_default.margin_required
