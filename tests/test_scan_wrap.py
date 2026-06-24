"""Tests for wrap assessment in scan."""

from __future__ import annotations

from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen

from lib.analyze import analyze_font
from lib.wrap_assess import assess_wrap_status, is_wrappable_sfnt
from tests.conftest import _empty_glyph, minimal_font


def _minimal_cff_font(glyph_names: list[str]):
    fb = FontBuilder(1000, isTTF=False)
    fb.setupGlyphOrder(glyph_names)
    cmap = {97: "a"} if "a" in glyph_names else {0xA0: ".notdef"}
    fb.setupCharacterMap(cmap)
    pen = T2CharStringPen(1000, None)
    pen.moveTo((0, 0))
    pen.lineTo((500, 0))
    pen.lineTo((500, 500))
    pen.closePath()
    charstring = pen.getCharString()
    fb.setupCFF(
        "Test-Regular",
        {"FamilyName": "Test", "FullName": "Test Regular"},
        {name: charstring for name in glyph_names},
        {},
    )
    return fb.font


def test_cff_font_is_wrappable():
    font = _minimal_cff_font([".notdef", "a", "a.sc"])
    assert is_wrappable_sfnt(font)


def test_cff_needs_scaffolding_when_no_gsub():
    font = _minimal_cff_font([".notdef", "a", "a.sc"])
    wrap = assess_wrap_status(font)
    assert wrap.needs_scaffolding
    assert wrap.can_wrap
    assert wrap.outline_kind == "cff"


def test_otl_stripped_suspected_when_glyphs_but_empty_otl():
    font = minimal_font([".notdef", "a", "a.sc"])
    audit = analyze_font(font, Path("Test.otf"))
    assert audit.wrap_status.needs_scaffolding
    assert audit.otl_stripped_suspected
    assert any(r.tag == "smcp" for r in audit.recommendations)
