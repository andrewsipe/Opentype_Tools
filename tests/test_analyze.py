"""Tests for FontFeatureAudit analysis."""

from __future__ import annotations

from pathlib import Path

from fontTools.ttLib import newTable
from fontTools.ttLib.tables import otTables

from lib.analyze import analyze_font
from lib.models import FeatureState
from tests.conftest import minimal_font


def test_smcp_inactive_when_glyphs_exist_no_feature():
    font = minimal_font([".notdef", "a", "a.sc"])
    audit = analyze_font(font, Path("Test.ttf"))
    smcp = audit.features["smcp"]
    assert smcp.state == FeatureState.INACTIVE
    assert smcp.missing_pairs == [("a", "a.sc")]


def test_smcp_active_when_sub_wired():
    font = minimal_font([".notdef", "a", "a.sc"])

    gsub = newTable("GSUB")
    gsub.table = otTables.GSUB()
    gsub.table.Version = 0x00010000
    gsub.table.ScriptList = otTables.ScriptList()
    gsub.table.ScriptList.ScriptCount = 0
    gsub.table.FeatureList = otTables.FeatureList()
    gsub.table.LookupList = otTables.LookupList()

    lookup = otTables.Lookup()
    lookup.LookupType = 1
    lookup.LookupFlag = 0
    subtable = otTables.SingleSubst()
    subtable.mapping = {"a": "a.sc"}
    lookup.SubTable = [subtable]
    gsub.table.LookupList.Lookup = [lookup]
    gsub.table.LookupList.LookupCount = 1

    feature = otTables.Feature()
    feature.LookupListIndex = [0]
    feature.LookupCount = 1
    frec = otTables.FeatureRecord()
    frec.FeatureTag = "smcp"
    frec.Feature = feature
    gsub.table.FeatureList.FeatureRecord = [frec]
    gsub.table.FeatureList.FeatureCount = 1
    font["GSUB"] = gsub

    audit = analyze_font(font, Path("Test.ttf"))
    assert audit.features["smcp"].state == FeatureState.ACTIVE


def test_glyph_inventory_counts_variants():
    font = minimal_font([".notdef", "a", "a.sc", "f", "f_f"])
    audit = analyze_font(font, Path("Test.ttf"))
    assert audit.glyph_inventory.glyph_count == 5
    assert audit.glyph_inventory.variant_glyph_count >= 1
    assert audit.glyph_inventory.has_variant_glyphs


def test_limited_glyph_set_warning_when_no_variants():
    glyphs = [".notdef", "a", "b", "c", "one", "two"]
    font = minimal_font(glyphs)
    audit = analyze_font(font, Path("Trial.ttf"))
    assert audit.glyph_inventory.limited_glyph_set
    assert not audit.glyph_inventory.has_variant_glyphs
    assert any("trial" in w.lower() or "subset" in w.lower() for w in audit.warnings)


def test_frac_inactive_with_numerator_denominator_glyphs():
    glyphs = [".notdef", "one", "two", "one.numerator", "two.denominator", "fraction"]
    font = minimal_font(glyphs)
    audit = analyze_font(font, Path("Test.ttf"))
    frac = audit.features["frac"]
    assert frac.state == FeatureState.INACTIVE
    assert len(frac.missing_pairs) == 2
