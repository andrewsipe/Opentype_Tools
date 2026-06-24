"""Tests that connect merge preserves existing GSUB features."""

from __future__ import annotations

from fontTools.ttLib import newTable
from fontTools.ttLib.tables import otTables

from lib.analyze import get_existing_feature_tags
from lib.feature_apply import apply_features_to_font
from tests.conftest import minimal_font


def _add_smcp_gsub(font):
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

    script = otTables.ScriptRecord()
    script.ScriptTag = "latn"
    script.Script = otTables.Script()
    langsys = otTables.LangSys()
    langsys.FeatureIndex = [0]
    langsys.FeatureCount = 1
    langsys.ReqFeatureIndex = 0xFFFF
    langsys.LookupOrder = None
    script.Script.DefaultLangSys = langsys
    script.Script.LangSysRecord = []
    script.Script.LangSysCount = 0
    gsub.table.ScriptList.ScriptRecord = [script]
    gsub.table.ScriptList.ScriptCount = 1

    font["GSUB"] = gsub


def test_merge_preserves_existing_features_when_adding_salt():
    font = minimal_font([".notdef", "a", "a.sc", "a.alt", "a.alt01"])
    _add_smcp_gsub(font)

    connect_fea = """feature salt {
  sub a by a.alt;
} salt;
"""
    ok, messages = apply_features_to_font(font, connect_fea, merge_mode=True)
    assert ok

    all_tags, _, _ = get_existing_feature_tags(font)
    assert "smcp" in all_tags
    assert "salt" in all_tags
    assert len(font["GSUB"].table.LookupList.Lookup) >= 2
