"""Tests for scan analysis quality (classification, OTL inventory, recommendations)."""

from __future__ import annotations

from pathlib import Path

from fontTools.ttLib import newTable
from fontTools.ttLib.tables import otTables

from lib.analyze import analyze_font
from lib.models import FeatureState
from lib.otl_inventory import analyze_installed_features
from tests.conftest import minimal_font


def _add_rlig_ligature(font, components: list[str], lig_glyph: str) -> None:
    gsub = newTable("GSUB")
    gsub.table = otTables.GSUB()
    gsub.table.Version = 0x00010000
    gsub.table.ScriptList = otTables.ScriptList()
    gsub.table.ScriptList.ScriptCount = 0
    gsub.table.FeatureList = otTables.FeatureList()
    gsub.table.LookupList = otTables.LookupList()

    lookup = otTables.Lookup()
    lookup.LookupType = 4
    lookup.LookupFlag = 0
    subtable = otTables.LigatureSubst()
    lig = otTables.Ligature()
    lig.Component = components[1:]
    lig.LigGlyph = lig_glyph
    subtable.ligatures = {components[0]: [lig]}
    lookup.SubTable = [subtable]
    gsub.table.LookupList.Lookup = [lookup]
    gsub.table.LookupList.LookupCount = 1

    feature = otTables.Feature()
    feature.LookupListIndex = [0]
    feature.LookupCount = 1
    frec = otTables.FeatureRecord()
    frec.FeatureTag = "rlig"
    frec.Feature = feature
    gsub.table.FeatureList.FeatureRecord = [frec]
    gsub.table.FeatureList.FeatureCount = 1
    font["GSUB"] = gsub


def test_liga_not_gap_when_ligatures_wired_under_rlig():
    font = minimal_font([".notdef", "f", "i", "fi"])
    font["cmap"].tables[0].cmap.update({0x66: "f", 0x69: "i", 0xFB01: "fi"})
    _add_rlig_ligature(font, ["f", "i"], "fi")
    audit = analyze_font(font, Path("Test.ttf"))
    liga = audit.features["liga"]
    assert liga.state == FeatureState.ACTIVE
    assert not liga.has_gaps
    assert not any(r.tag == "liga" for r in audit.recommendations)


def test_installed_feature_populated_vs_empty():
    font = minimal_font([".notdef", "a", "a.sc"])

    gsub = newTable("GSUB")
    gsub.table = otTables.GSUB()
    gsub.table.Version = 0x00010000
    gsub.table.ScriptList = otTables.ScriptList()
    gsub.table.ScriptList.ScriptCount = 0
    gsub.table.FeatureList = otTables.FeatureList()
    gsub.table.LookupList = otTables.LookupList()
    gsub.table.LookupList.Lookup = []
    gsub.table.LookupList.LookupCount = 0

    empty_feat = otTables.Feature()
    empty_feat.LookupListIndex = []
    empty_feat.LookupCount = 0
    empty_rec = otTables.FeatureRecord()
    empty_rec.FeatureTag = "liga"
    empty_rec.Feature = empty_feat

    lookup = otTables.Lookup()
    lookup.LookupType = 1
    lookup.LookupFlag = 0
    subtable = otTables.SingleSubst()
    subtable.mapping = {"a": "a.sc"}
    lookup.SubTable = [subtable]
    gsub.table.LookupList.Lookup = [lookup]
    gsub.table.LookupList.LookupCount = 1

    smcp_feat = otTables.Feature()
    smcp_feat.LookupListIndex = [0]
    smcp_feat.LookupCount = 1
    smcp_rec = otTables.FeatureRecord()
    smcp_rec.FeatureTag = "smcp"
    smcp_rec.Feature = smcp_feat

    gsub.table.FeatureList.FeatureRecord = [empty_rec, smcp_rec]
    gsub.table.FeatureList.FeatureCount = 2
    font["GSUB"] = gsub

    installed = analyze_installed_features(font)
    assert installed["liga"].populated is False
    assert installed["liga"].status_label == "empty"
    assert installed["smcp"].populated is True

    audit = analyze_font(font, Path("Test.ttf"))
    assert audit.features["smcp"].state == FeatureState.ACTIVE
    assert "liga" in audit.installed_features
