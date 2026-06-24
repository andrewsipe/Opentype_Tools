"""Tests for aalt feature builder."""

from __future__ import annotations

from fontTools.ttLib import newTable
from fontTools.ttLib.tables import otTables

from lib.aalt_builder import (
    apply_aalt_to_font,
    build_aalt_plan,
    generate_aalt_fea,
    gsub_has_unsupported_lookups,
)
from lib.analyze import get_existing_feature_tags
from lib.feature_policy import aalt_source_tags
from lib.models import InstalledFeatureDetail
from lib.wrapper_helpers import apply_feature_text, create_gpos, create_gsub
from tests.conftest import minimal_font


def _installed_gsub(tag: str, *, populated: bool = True) -> dict:
    return {
        tag: InstalledFeatureDetail(
            tag=tag,
            table="GSUB",
            lookup_count=1,
            populated=populated,
            in_naming_policy=True,
        )
    }


def test_aalt_source_tag_ordering():
    installed = {
        **_installed_gsub("ss02"),
        **_installed_gsub("liga"),
        **_installed_gsub("cv02"),
        **_installed_gsub("ss01"),
        **_installed_gsub("zzzz"),
    }
    assert aalt_source_tags(installed) == [
        "liga",
        "ss01",
        "ss02",
        "cv02",
        "zzzz",
    ]


def test_generate_aalt_fea_references_features():
    fea = generate_aalt_fea(
        {"a": ["a", "a.ss01"]},
        ligature_tags=["liga", "ss01"],
    )
    assert "sub a from [a a.ss01];" in fea
    assert "Ligature lookups included: liga, ss01" in fea
    assert fea.strip().endswith("} aalt;")


def test_apply_aalt_preserves_liga_and_gpos():
    font = minimal_font([".notdef", "f", "i", "fi"])
    create_gsub(font)
    create_gpos(font)
    liga_fea = "feature liga {\n  sub f i by fi;\n} liga;\n"
    kern_fea = "feature kern {\n  pos f i -20;\n} kern;\n"
    apply_feature_text(font, liga_fea)
    apply_feature_text(font, kern_fea)

    ok, messages = apply_aalt_to_font(font)
    assert ok, messages

    all_tags, gsub_tags, gpos_tags = get_existing_feature_tags(font)
    assert "liga" in gsub_tags
    assert "aalt" in gsub_tags
    assert "kern" in gpos_tags
    assert "GPOS" in font


def test_apply_aalt_blocked_on_unsupported_lookup():
    font = minimal_font([".notdef", "a", "a.alt"])
    from lib.otl_inventory import analyze_installed_features

    gsub = newTable("GSUB")
    gsub.table = otTables.GSUB()
    gsub.table.Version = 0x00010000
    gsub.table.ScriptList = otTables.ScriptList()
    gsub.table.ScriptList.ScriptCount = 0
    gsub.table.FeatureList = otTables.FeatureList()
    gsub.table.LookupList = otTables.LookupList()

    lookup = otTables.Lookup()
    lookup.LookupType = 3
    lookup.LookupFlag = 0
    lookup.SubTable = [otTables.AlternateSubst()]
    gsub.table.LookupList.Lookup = [lookup]
    gsub.table.LookupList.LookupCount = 1

    feature = otTables.Feature()
    feature.LookupListIndex = [0]
    feature.LookupCount = 1
    frec = otTables.FeatureRecord()
    frec.FeatureTag = "salt"
    frec.Feature = feature
    gsub.table.FeatureList.FeatureRecord = [frec]
    gsub.table.FeatureList.FeatureCount = 1
    font["GSUB"] = gsub

    assert gsub_has_unsupported_lookups(font)
    installed = analyze_installed_features(font)
    assert "salt" in installed
    plan = build_aalt_plan(font)
    assert plan.blocked

    ok, messages = apply_aalt_to_font(font)
    assert not ok
    assert messages
