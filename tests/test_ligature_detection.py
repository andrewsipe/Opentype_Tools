"""Tests for ligature glyph detection (underscore, Unicode, and short names)."""

from __future__ import annotations

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from lib.detection import UnifiedGlyphDetector
from lib.feature_policy import LIGATURE_GLYPH_POLICY, LIGATURE_GLYPH_NAME_COMPONENTS


def _empty_glyph():
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((10, 0))
    pen.lineTo((10, 10))
    pen.closePath()
    return pen.glyph()


def _font_with_ligatures():
    names = [".notdef", "f", "i", "l", "s", "t", "f_f", "fi", "fl", "s_t"]
    fb = FontBuilder(1000, isTTF=True)
    empty = _empty_glyph()
    fb.setupGlyf({name: empty for name in names})
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap(
        {
            0x66: "f",
            0x69: "i",
            0x6C: "l",
            0x73: "s",
            0x74: "t",
            0xFB01: "fi",
            0xFB02: "fl",
        }
    )
    return fb.font


def test_ligature_glyph_policy_covers_fi_fl():
    assert LIGATURE_GLYPH_NAME_COMPONENTS["fi"] == ("f", "i")
    assert LIGATURE_GLYPH_NAME_COMPONENTS["fl"] == ("f", "l")
    assert any("fi" in e.glyph_names for e in LIGATURE_GLYPH_POLICY)


def test_detects_underscore_and_unicode_ligatures():
    font = _font_with_ligatures()
    detected = UnifiedGlyphDetector(font).get_features()
    liga = {tuple(c): g for c, g in detected["liga"]}
    dlig = {tuple(c): g for c, g in detected["dlig"]}
    assert ("f", "f") in liga and liga[("f", "f")] == "f_f"
    assert ("f", "i") in liga and liga[("f", "i")] == "fi"
    assert ("f", "l") in liga and liga[("f", "l")] == "fl"
    assert ("s", "t") in dlig and dlig[("s", "t")] == "s_t"


def test_zurika_style_missing_fi_fl_in_partial_liga():
    """Wrapped Zurika has f_f rules but not f+i -> fi until connect fills the gap."""
    from pathlib import Path

    path = Path("/Users/skymacbook/Downloads/ROHH_Trial_Fonts/Zurika-Regular.otf")
    if not path.exists():
        return

    from fontTools.ttLib import TTFont

    from lib.analyze import analyze_font

    with TTFont(path) as font:
        audit = analyze_font(font, path)
    liga = audit.features["liga"]
    missing = {tuple(c): g for c, g in liga.missing_ligatures}
    if not missing:
        return
    assert ("f", "i") in missing
    assert missing[("f", "i")] == "fi"
    assert ("f", "l") in missing
    assert missing[("f", "l")] == "fl"
