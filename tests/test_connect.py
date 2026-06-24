"""Tests for connect plan generation."""

from __future__ import annotations

from pathlib import Path

from fontTools.ttLib import newTable
from fontTools.ttLib.tables import otTables

from lib.analyze import analyze_font
from lib.connect import build_connect_plan, render_connect_fea
from lib.models import FeatureState
from tests.conftest import add_empty_otl_shell, minimal_font


def test_connect_fea_includes_smcp_subs():
    font = minimal_font([".notdef", "a", "a.sc"])
    add_empty_otl_shell(font)
    path = Path("Test.ttf")
    audit = analyze_font(font, path)
    plan = build_connect_plan(audit)
    assert plan.has_work
    fea = render_connect_fea(audit, plan, font)
    assert "feature smcp" in fea
    assert "sub a by a.sc" in fea


def test_connect_plan_empty_when_active():
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
    plan = build_connect_plan(audit)
    assert not plan.has_work
