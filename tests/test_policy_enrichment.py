"""Tests for Glyphs-derived policy data: suffixes, ligature tiers, conflicts."""

from __future__ import annotations

from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import newTable
from fontTools.ttLib.tables import otTables

from lib.analyze import analyze_font
from lib.detection import UnifiedGlyphDetector
from lib.feature_policy import ligature_tier_for_glyph
from lib.policy_data import feature_label, installed_conflict_for
from lib.recommendations import tier_for_gap
from lib.models import InstalledFeatureDetail, RecommendTier
from tests.conftest import minimal_font


def _empty_glyph():
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((10, 0))
    pen.lineTo((10, 10))
    pen.closePath()
    return pen.glyph()


def _font_with_figure_suffixes():
    names = [".notdef", "one", "one.osf", "one.lf", "one.tf", "a", "a.smcp"]
    fb = FontBuilder(1000, isTTF=True)
    empty = _empty_glyph()
    fb.setupGlyf({name: empty for name in names})
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({0x31: "one", 0x61: "a"})
    return fb.font


def _add_single_subst_feature(font, tag: str, mapping: dict[str, str]) -> None:
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
    subtable.mapping = mapping
    lookup.SubTable = [subtable]
    gsub.table.LookupList.Lookup = [lookup]
    gsub.table.LookupList.LookupCount = 1

    feature = otTables.Feature()
    feature.LookupListIndex = [0]
    feature.LookupCount = 1
    frec = otTables.FeatureRecord()
    frec.FeatureTag = tag
    frec.Feature = feature
    gsub.table.FeatureList.FeatureRecord = [frec]
    gsub.table.FeatureList.FeatureCount = 1
    font["GSUB"] = gsub


def test_glyphs_figure_suffixes_detected():
    font = _font_with_figure_suffixes()
    features = UnifiedGlyphDetector(font).get_features()
    assert ("one", "one.osf") in features["onum"]
    assert ("one", "one.lf") in features["lnum"]
    assert ("one", "one.tf") in features["tnum"]
    assert ("a", "a.smcp") in features["smcp"]


def test_ligature_tier_routing():
    assert ligature_tier_for_glyph("fi", ("f", "i")) == "liga"
    assert ligature_tier_for_glyph("g_h", ("g", "h")) == "dlig"
    assert ligature_tier_for_glyph("f_f", ("f", "f")) == "liga"
    assert ligature_tier_for_glyph("ornament.dlig", ("o", "r")) == "dlig"
    assert ligature_tier_for_glyph("ff.liga", ("f", "f")) == "liga"
    assert ligature_tier_for_glyph("st", ("s", "t")) == "dlig"


def test_feature_label_from_registry():
    assert feature_label("liga") == "Standard Ligatures"
    assert feature_label("ss01") == "Stylistic Set 01"
    assert feature_label("cv03") == "Character Variant 03"
    assert feature_label("unknown", fallback="Fallback") == "Fallback"


def test_onum_skipped_when_lnum_populated():
    font = minimal_font([".notdef", "one", "one.osf", "one.lf"])
    _add_single_subst_feature(font, "lnum", {"one": "one.lf"})
    audit = analyze_font(font, Path("Test.ttf"))
    onum = audit.features["onum"]
    assert onum.has_gaps
    tier, reason = tier_for_gap("onum", onum, audit)
    assert tier == RecommendTier.SKIP
    assert "lnum" in reason
    assert not any(r.tag == "onum" for r in audit.recommendations)


def test_installed_conflict_for_ignores_empty_shell():
    conflict = installed_conflict_for(
        "onum",
        {"lnum"},
        installed_features={
            "lnum": InstalledFeatureDetail(
                tag="lnum",
                table="GSUB",
                lookup_count=1,
                populated=False,
                in_naming_policy=True,
            )
        },
    )
    assert conflict is None
