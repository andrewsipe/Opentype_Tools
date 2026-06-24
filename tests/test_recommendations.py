"""Tests for graded scan recommendations and connect filtering."""

from __future__ import annotations

from pathlib import Path

from fontTools.ttLib import newTable
from fontTools.ttLib.tables import otTables

from lib.analyze import analyze_font
from lib.connect import build_connect_plan
from lib.models import RecommendTier
from lib.recommendations import compute_recommendations, tier_for_gap
from tests.conftest import minimal_font


def test_salt_skipped_when_ss01_glyphs_present():
    font = minimal_font([".notdef", "a", "a.alt", "a.ss01"])
    audit = analyze_font(font, Path("Test.ttf"))
    salt = audit.features["salt"]
    assert salt.has_gaps
    assert not any(r.tag == "salt" for r in audit.recommendations)
    tier, reason = tier_for_gap("salt", salt, audit)
    assert tier == RecommendTier.SKIP
    assert "ss01" in reason


def test_smcp_recommended_high():
    font = minimal_font([".notdef", "a", "a.sc"])
    audit = analyze_font(font, Path("Test.ttf"))
    rec = next(r for r in audit.recommendations if r.tag == "smcp")
    assert rec.tier == RecommendTier.HIGH


def test_connect_excludes_low_tier_salt():
    font = minimal_font([".notdef", "a", "a.alt"])
    audit = analyze_font(font, Path("Test.ttf"))
    rec = next(r for r in audit.recommendations if r.tag == "salt")
    assert rec.tier == RecommendTier.LOW
    plan = build_connect_plan(audit)
    assert not plan.has_work


def test_frac_manual_tier_in_scan_not_connect():
    glyphs = [".notdef", "one", "two", "one.numerator", "two.denominator", "fraction"]
    font = minimal_font(glyphs)
    audit = analyze_font(font, Path("Test.ttf"))
    frac_rec = next(r for r in audit.recommendations if r.tag == "frac")
    assert frac_rec.tier == RecommendTier.MANUAL
    plan = build_connect_plan(audit)
    assert plan.features.get("frac") is None
