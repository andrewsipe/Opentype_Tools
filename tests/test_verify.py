"""Tests for post-workflow verify checks."""

from __future__ import annotations

from pathlib import Path

from fontTools.ttLib import newTable
from fontTools.ttLib.tables import otTables

from lib.verify import VerifySeverity, verify_font, verify_passes
from tests.conftest import add_empty_otl_shell, minimal_font


def _add_liga_without_script(font, components: list[str], lig_glyph: str) -> None:
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
    lig.CompCount = len(components)
    subtable.ligatures = {components[0]: [lig]}
    lookup.SubTable = [subtable]
    gsub.table.LookupList.Lookup = [lookup]
    gsub.table.LookupList.LookupCount = 1

    feature = otTables.Feature()
    feature.LookupListIndex = [0]
    feature.LookupCount = 1
    frec = otTables.FeatureRecord()
    frec.FeatureTag = "liga"
    frec.Feature = feature
    gsub.table.FeatureList.FeatureRecord = [frec]
    gsub.table.FeatureList.FeatureCount = 1
    font["GSUB"] = gsub


def test_verify_passes_clean_font():
    font = minimal_font([".notdef", "f", "i", "fi"])
    add_empty_otl_shell(font)
    _add_liga_without_script(font, ["f", "i"], "fi")
    path = Path("Clean-Regular.ttf")
    report = verify_font(font, path)
    assert verify_passes(report)
    assert not report.errors


def test_verify_fails_on_empty_script_list_warning():
    font = minimal_font([".notdef", "f", "i", "fi"])
    _add_liga_without_script(font, ["f", "i"], "fi")
    path = Path("NoScript-Regular.ttf")
    report = verify_font(font, path)
    assert any(
        f.severity == VerifySeverity.WARNING and "ScriptList" in f.message
        for f in report.findings
    )
    assert verify_passes(report)
    assert not verify_passes(report, strict=True)


def test_verify_fails_on_partial_liga_gap():
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    def _glyph():
        pen = TTGlyphPen(None)
        pen.moveTo((0, 0))
        pen.lineTo((10, 0))
        pen.lineTo((10, 10))
        pen.closePath()
        return pen.glyph()

    names = [".notdef", "f", "i", "l", "fi", "fl", "f_f"]
    fb = FontBuilder(1000, isTTF=True)
    empty = _glyph()
    fb.setupGlyf({name: empty for name in names})
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap(
        {
            0x66: "f",
            0x69: "i",
            0x6C: "l",
            0xFB01: "fi",
            0xFB02: "fl",
        }
    )
    font = fb.font
    _add_liga_without_script(font, ["f", "f"], "f_f")
    path = Path("PartialLiga-Regular.ttf")
    report = verify_font(font, path)
    assert any(f.severity == VerifySeverity.ERROR for f in report.findings)
    assert not verify_passes(report)
