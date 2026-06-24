"""Tests for wrap kern migration preserving GSUB on OTF fonts."""

from __future__ import annotations

from pathlib import Path

from lib.wrapper_helpers import (
    apply_feature_text,
    create_gsub,
    ensure_otl_scaffolding,
    fea_target_tables,
)
from tests.conftest import minimal_font


def test_fea_target_tables_kern_is_gpos_only():
    fea = "feature kern {\n  pos a b 50;\n} kern;\n"
    assert fea_target_tables(fea) == ["GPOS"]


def test_fea_target_tables_liga_is_gsub_only():
    fea = "feature liga {\n  sub f i by fi;\n} liga;\n"
    assert fea_target_tables(fea) == ["GSUB"]


def test_kern_migration_preserves_gsub():
    font = minimal_font([".notdef", "a", "b"])
    create_gsub(font)
    fea = "feature kern {\n  pos a b -50;\n} kern;\n"
    ok, _ = apply_feature_text(font, fea)
    assert ok
    assert "GSUB" in font
    assert "GPOS" in font
    assert font["GPOS"].table.FeatureList.FeatureRecord[0].FeatureTag == "kern"


def test_ensure_otl_scaffolding_restores_gsub():
    font = minimal_font([".notdef", "a"])
    msgs = ensure_otl_scaffolding(font)
    assert "GSUB" in font
    assert any("GSUB" in m for m in msgs)
