"""Tests for connect prerequisites, tiers, and preview."""

from __future__ import annotations

from pathlib import Path

from lib.analyze import analyze_font
from lib.connect import build_connect_plan, connect_block_reason, render_connect_fea
from lib.models import ConnectOptions
from tests.conftest import add_empty_otl_shell, minimal_font


def test_connect_blocked_when_gsub_missing():
    font = minimal_font([".notdef", "a", "a.sc"])
    audit = analyze_font(font, Path("Trial.ttf"))
    assert connect_block_reason(audit) is not None
    plan = build_connect_plan(audit)
    assert plan.blocked
    assert not plan.has_work


def test_connect_allowed_with_empty_gsub_shell():
    font = minimal_font([".notdef", "a", "a.sc"])
    add_empty_otl_shell(font)
    audit = analyze_font(font, Path("Test.ttf"))
    assert connect_block_reason(audit) is None
    plan = build_connect_plan(audit)
    assert not plan.blocked
    assert plan.has_work


def test_connect_blocked_for_trial_glyph_set():
    glyphs = [".notdef", "a", "b", "one"]
    font = minimal_font(glyphs)
    audit = analyze_font(font, Path("Trial.ttf"))
    assert "Trial" in (connect_block_reason(audit) or "")
    plan = build_connect_plan(audit)
    assert plan.blocked


def test_connect_include_low_for_salt():
    font = minimal_font([".notdef", "a", "a.alt"])
    add_empty_otl_shell(font)
    audit = analyze_font(font, Path("Test.ttf"))
    default = build_connect_plan(audit)
    assert not any(tag == "salt" for tag in default.features)

    with_low = build_connect_plan(audit, ConnectOptions(include_low=True))
    assert "salt" in with_low.features
    fea = render_connect_fea(audit, with_low, font)
    assert "feature salt" in fea


def test_connect_skips_zero_work_features():
    font = minimal_font([".notdef", "a", "a.sc"])
    add_empty_otl_shell(font)
    audit = analyze_font(font, Path("Test.ttf"))
    plan = build_connect_plan(audit, ConnectOptions())
    assert not plan.blocked
    assert plan.has_work
