"""Tests for GDEF mark-glyph inference heuristics."""

from __future__ import annotations

from lib.wrapper_helpers import _detect_mark_glyphs, _glyph_name_suggests_mark
from tests.conftest import minimal_font


def test_glyph_name_suggests_mark_tokens():
    assert _glyph_name_suggests_mark("acutecomb")
    assert _glyph_name_suggests_mark("grave_comb")
    assert _glyph_name_suggests_mark("dotaccent.mark")
    assert not _glyph_name_suggests_mark("trademark")
    assert not _glyph_name_suggests_mark("nonmarkingreturn")


def test_trademark_not_classified_as_mark():
    font = minimal_font([".notdef", "trademark", "registered", "acutecomb"])
    font["cmap"] = font["cmap"]  # keep default cmap from minimal_font
    marks = _detect_mark_glyphs(font)
    assert "acutecomb" in marks
    assert "trademark" not in marks
    assert "registered" not in marks
