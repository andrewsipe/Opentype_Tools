"""Shared fixtures for Opentype_Tools tests."""

from __future__ import annotations

import sys
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import newTable
from fontTools.ttLib.tables import otTables

from lib.wrapper_helpers import empty_otl_table

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


def _empty_glyph():
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((10, 0))
    pen.lineTo((10, 10))
    pen.closePath()
    return pen.glyph()


def minimal_font(glyph_names: list[str]):
    """Build a minimal TrueType font with the given glyph names."""
    fb = FontBuilder(1000, isTTF=True)
    empty = _empty_glyph()
    fb.setupGlyf({name: empty for name in glyph_names})
    fb.setupGlyphOrder(glyph_names)
    cmap = {}
    if "a" in glyph_names:
        cmap[97] = "a"
    if "A" in glyph_names:
        cmap[65] = "A"
    if "one" in glyph_names:
        cmap[49] = "one"
    fb.setupCharacterMap(cmap or {0xA0: ".notdef"})
    return fb.font


def add_empty_otl_shell(font) -> None:
    """Add empty GSUB/GDEF/GPOS so connect can merge rules (post-wrap shape)."""
    if "GSUB" not in font:
        gsub = newTable("GSUB")
        gsub.table = empty_otl_table(otTables.GSUB)
        font["GSUB"] = gsub

    if "GDEF" not in font:
        gdef = newTable("GDEF")
        gdef.table = otTables.GDEF()
        gdef.table.Version = 0x00010000
        gdef.table.GlyphClassDef = None
        gdef.table.AttachList = None
        gdef.table.LigCaretList = None
        font["GDEF"] = gdef

    if "GPOS" not in font:
        gpos = newTable("GPOS")
        gpos.table = empty_otl_table(otTables.GPOS)
        font["GPOS"] = gpos
