"""
Wrapper helper functions for OpenType table scaffolding and enrichment.

Functions for creating OpenType tables (cmap, GDEF, GSUB, GPOS) and enriching fonts
with inferred features like ligatures and kerning.
"""

import unicodedata
import warnings
from typing import Dict, List, Optional, Set, Tuple

from fontTools.agl import toUnicode
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import otTables
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable

from .config import CONFIG
from .detection import UnifiedGlyphDetector

# Try to import feaLib
try:
    from fontTools.feaLib.builder import addOpenTypeFeaturesFromString

    HAVE_FEALIB = True
except Exception:
    HAVE_FEALIB = False
    addOpenTypeFeaturesFromString = None

# Try to import buildGDEF
try:
    from fontTools.otlLib.builder import buildGDEF as _buildGDEF

    HAVE_BUILDGDEF = True
except Exception:
    HAVE_BUILDGDEF = False
    _buildGDEF = None


def _derive_unicode_map_from_glyph_names(font: TTFont) -> Dict[int, str]:
    """Derive a Unicode mapping from glyph names using AGL rules."""
    mapping: Dict[int, str] = {}
    for glyph_name in font.getGlyphOrder():
        if glyph_name in CONFIG.SPECIAL_GLYPHS:
            continue
        try:
            uni = toUnicode(glyph_name)
        except Exception:
            uni = None
        if not uni:
            continue
        if len(uni) != 1:
            continue
        cp = ord(uni)
        if cp not in mapping:
            mapping[cp] = glyph_name
    return mapping


def _font_has_windows_unicode_cmap(font: TTFont) -> bool:
    """Check if font has Windows Unicode cmap."""
    if "cmap" not in font:
        return False
    try:
        for sub in font["cmap"].tables:
            if sub.platformID == 3 and sub.platEncID in (1, 10):
                if getattr(sub, "cmap", None):
                    return True
    except Exception:
        return False
    return False


def create_cmap(
    font: TTFont, overwrite_unicode: bool = False
) -> Tuple[bool, List[str]]:
    """Ensure a Windows Unicode cmap exists."""
    messages: List[str] = []

    existing_best = {}
    try:
        existing_best = font.getBestCmap() or {}
    except Exception:
        existing_best = {}

    if existing_best and not overwrite_unicode and _font_has_windows_unicode_cmap(font):
        messages.append("Unicode cmap present; no change")
        return False, messages

    derived = _derive_unicode_map_from_glyph_names(font)
    if existing_best:
        for cp, g in existing_best.items():
            derived.setdefault(cp, g)

    if not derived:
        messages.append("Unable to derive any Unicode mapping from glyph names")
        return False, messages

    need_u32 = any(cp > 0xFFFF for cp in derived)

    # Same predicate as branch below — drives user message (don't rely on
    # "cmap" in font after we assign font["cmap"] later).
    using_new_cmap_shell = ("cmap" not in font) or overwrite_unicode

    if using_new_cmap_shell:
        cmap_table = newTable("cmap")
        cmap_table.tableVersion = 0
        cmap_table.tables = []
    else:
        cmap_table = font["cmap"]

    bmp_map = {cp: g for cp, g in derived.items() if cp <= 0xFFFF}
    if bmp_map:
        st4 = CmapSubtable.newSubtable(4)
        st4.platformID = 3
        st4.platEncID = 1
        st4.language = 0
        st4.cmap = bmp_map
        cmap_table.tables.append(st4)

    if need_u32:
        st12 = CmapSubtable.newSubtable(12)
        st12.platformID = 3
        st12.platEncID = 10
        st12.language = 0
        st12.cmap = derived
        cmap_table.tables.append(st12)

    fmt = "format 4" + (" + 12" if need_u32 else "")
    if using_new_cmap_shell:
        summary = f"Created Unicode cmap ({fmt})"
    else:
        summary = f"Added Windows Unicode subtable(s) ({fmt})"

    font["cmap"] = cmap_table
    messages.append(summary)
    return True, messages


def create_gdef(font: TTFont, overwrite: bool = False) -> Tuple[bool, str]:
    """Ensure GDEF table exists."""
    if "GDEF" in font and not overwrite:
        return False, "GDEF present; no change"
    gdef = newTable("GDEF")
    gdef.table = otTables.GDEF()
    gdef.table.Version = 0x00010000
    gdef.table.GlyphClassDef = None
    gdef.table.AttachList = None
    gdef.table.LigCaretList = None
    gdef.table.MarkAttachClassDef = None
    gdef.table.MarkGlyphSetsDef = None
    font["GDEF"] = gdef
    return True, "Created empty GDEF"


def empty_otl_table(table_cls: type) -> object:
    """Create empty GSUB/GPOS-style OTL table structure (ScriptList, FeatureList, LookupList)."""
    tbl = table_cls()
    tbl.Version = 0x00010000
    sl = otTables.ScriptList()
    sl.ScriptCount = 0
    sl.ScriptRecord = []
    fl = otTables.FeatureList()
    fl.FeatureCount = 0
    fl.FeatureRecord = []
    ll = otTables.LookupList()
    ll.LookupCount = 0
    ll.Lookup = []
    tbl.ScriptList = sl
    tbl.FeatureList = fl
    tbl.LookupList = ll
    return tbl


def create_gpos(font: TTFont, overwrite: bool = False) -> Tuple[bool, str]:
    """Ensure GPOS table exists."""
    if "GPOS" in font and not overwrite:
        return False, "GPOS present; no change"
    gpos = newTable("GPOS")
    gpos.table = empty_otl_table(otTables.GPOS)
    font["GPOS"] = gpos
    return True, "Created empty GPOS"


def create_gsub(font: TTFont, overwrite: bool = False) -> Tuple[bool, str]:
    """Ensure GSUB table exists."""
    if "GSUB" in font and not overwrite:
        return False, "GSUB present; no change"
    gsub = newTable("GSUB")
    gsub.table = empty_otl_table(otTables.GSUB)
    font["GSUB"] = gsub
    return True, "Created empty GSUB"


def create_dsig_stub(font: TTFont, enable: bool) -> Tuple[bool, str]:
    """Ensure DSIG stub exists."""
    if not enable:
        return False, "DSIG disabled"
    if "DSIG" in font:
        return False, "DSIG present; no change"
    dsig = newTable("DSIG")
    dsig.ulVersion = 1
    dsig.usFlag = 0
    dsig.usNumSigs = 0
    dsig.signatureRecords = []
    font["DSIG"] = dsig
    return True, "Created DSIG stub"


def _invert_best_cmap(font: TTFont) -> Dict[str, List[int]]:
    """Return mapping glyphName -> list of codepoints from best cmap."""
    inv: Dict[str, List[int]] = {}
    try:
        best = font.getBestCmap() or {}
    except Exception:
        best = {}
    for cp, gname in best.items():
        inv.setdefault(gname, []).append(cp)
    return inv


def _detect_mark_glyphs(font: TTFont) -> Set[str]:
    """Detect mark glyphs by Unicode categories."""
    inv = _invert_best_cmap(font)
    marks: Set[str] = set()
    for g, cps in inv.items():
        for cp in cps:
            cat = unicodedata.category(chr(cp))
            if cat in ("Mn", "Mc", "Me"):
                marks.add(g)
                break
    for g in font.getGlyphOrder():
        lower = g.lower()
        if any(tok in lower for tok in ("comb", "mark")):
            marks.add(g)
    return marks


def infer_ligatures(font: TTFont) -> List[Tuple[List[str], str]]:
    """Return list of ([components...], ligatureGlyphName)."""
    detector = UnifiedGlyphDetector(font)
    return detector.get_features()["liga"]


def build_liga_feature_text(font: TTFont, ligs: List[Tuple[List[str], str]]) -> str:
    """Build liga feature text."""
    lines = ["feature liga {"]
    for comps, lig in ligs:
        lines.append(f"  sub {' '.join(comps)} by {lig};")
    lines.append("} liga;")
    return "\n".join(lines)


def build_kern_feature_text(font: TTFont) -> Optional[str]:
    """Build kern feature text from legacy kern table."""
    if "kern" not in font:
        return None
    try:
        k = font["kern"]
        subtables = getattr(k, "kernTables", None) or getattr(k, "tables", None)
    except Exception:
        return None
    if not subtables:
        return None
    glyph_order = set(font.getGlyphOrder())
    rules: List[str] = []
    for st in subtables:
        try:
            if getattr(st, "format", 0) != 0:
                continue
            table = getattr(st, "kernTable", None)
            if not table:
                continue
            for (left_glyph, right_glyph), val in table.items():
                if not isinstance(left_glyph, str) or not isinstance(right_glyph, str):
                    try:
                        left_glyph = font.getGlyphOrder()[left_glyph]
                        right_glyph = font.getGlyphOrder()[right_glyph]
                    except Exception:
                        continue
                if val == 0:
                    continue
                if left_glyph not in glyph_order or right_glyph not in glyph_order:
                    warnings.warn(
                        f"kern pair references missing glyph(s): "
                        f"{left_glyph!r} {right_glyph!r}; skipping",
                        UserWarning,
                        stacklevel=2,
                    )
                    continue
                rules.append(f"  pos {left_glyph} {right_glyph} {val};")
        except Exception:
            continue
    if not rules:
        return None
    return "\n".join(["feature kern {", *rules, "} kern;"])


def apply_feature_text(font: TTFont, feature_text: str) -> Tuple[bool, str]:
    """Apply feature text to font."""
    if not feature_text:
        return False, ""
    if not HAVE_FEALIB:
        return False, "feaLib not available; cannot build features"
    try:
        addOpenTypeFeaturesFromString(font, feature_text)
        return True, "features compiled"
    except Exception as e:
        return False, f"feature build failed: {e}"


def build_enriched_gdef(
    font: TTFont,
    use_classes: bool,
    add_carets: bool,
    ligs: Optional[List[Tuple[List[str], str]]] = None,
) -> Tuple[bool, str]:
    """Build enriched GDEF with classes and carets."""
    if not use_classes and not add_carets:
        return False, "GDEF enrichment disabled"

    class_map: Dict[str, int] = {}
    carets: Dict[str, List[int]] = {}

    marks = _detect_mark_glyphs(font) if use_classes else set()
    if ligs is None:
        ligs = infer_ligatures(font)
    lig_set = {lig for _, lig in ligs}

    if use_classes:
        for g in font.getGlyphOrder():
            if g in marks:
                class_map[g] = 3  # Mark
            elif g in lig_set:
                class_map[g] = 2  # Ligature
            else:
                class_map[g] = 1  # Base

    if add_carets and ligs:
        hmtx = font["hmtx"]
        for comps, lig in ligs:
            try:
                adv = hmtx[lig][0]
            except Exception:
                continue
            n = len(comps)
            if n >= 2 and adv > 0:
                carets[lig] = [int(adv * i / n) for i in range(1, n)]

    if not class_map and not carets:
        return False, "No GDEF data inferred"

    if HAVE_BUILDGDEF and _buildGDEF is not None:
        try:
            mark_sets = [marks] if marks else None
            gdef_table = _buildGDEF(
                glyphClassDef=class_map or None,
                attachList=None,
                ligCaretList=carets or None,
                markAttachClassDef=None,
                markGlyphSetsDef=mark_sets,
            )
            gdef = newTable("GDEF")
            gdef.table = gdef_table
            font["GDEF"] = gdef
            return True, "Enriched GDEF built"
        except Exception as e:
            return False, f"Failed to build enriched GDEF: {e}"
    else:
        try:
            gdef = newTable("GDEF")
            gdef.table = otTables.GDEF()
            gdef.table.Version = 0x00010000
            if class_map:
                cd = otTables.ClassDef()
                cd.classDefs = class_map
                gdef.table.GlyphClassDef = cd
            if carets:
                lcl = otTables.LigCaretList()
                lcl.LigGlyphCount = len(carets)
                lcl.LigGlyph = []
                cov = otTables.Coverage()
                cov.glyphs = list(carets.keys())
                lcl.Coverage = cov
                for lig, caret_positions in carets.items():
                    lg = otTables.LigGlyph()
                    lg.CaretCount = len(caret_positions)
                    lg.CaretValue = []
                    for x in caret_positions:
                        cv = otTables.CaretValue()
                        cv.Format = 1
                        cv.Coordinate = x
                        lg.CaretValue.append(cv)
                    lcl.LigGlyph.append(lg)
                gdef.table.LigCaretList = lcl
            font["GDEF"] = gdef
            return True, "Enriched GDEF (fallback) built"
        except Exception as e:
            return False, f"Failed to build enriched GDEF fallback: {e}"


def enrich_font(
    font: TTFont,
    do_kern_migration: bool,
    do_liga: bool,
    do_gdef_classes: bool,
    do_lig_carets: bool,
    drop_kern_after: bool,
    liga_list: Optional[List[Tuple[List[str], str]]] = None,
) -> Tuple[bool, List[str]]:
    """Enrich font with inferred features.

    ``liga_list`` if provided is used for the ``liga`` feature and GDEF ligature classes /
    carets instead of calling :func:`infer_ligatures` again (keeps planner and executor aligned).
    """
    changed = False
    messages: List[str] = []

    need_ligs = do_liga or do_gdef_classes or do_lig_carets
    if liga_list is not None:
        ligs_resolved: List[Tuple[List[str], str]] = list(liga_list)
    elif need_ligs:
        ligs_resolved = infer_ligatures(font)
    else:
        ligs_resolved = []

    if do_kern_migration:
        fea = build_kern_feature_text(font)
        if fea:
            # Count kern pairs before migration
            kern_count = len(
                [line for line in fea.split("\n") if line.strip().startswith("pos")]
            )
            ok, msg = apply_feature_text(font, fea)
            if ok:
                messages.append(f"Migrated {kern_count} kern pairs to GPOS")
            else:
                messages.append(f"Kern migration failed: {msg}")
            changed = changed or ok
            if ok and drop_kern_after and "kern" in font:
                try:
                    del font["kern"]
                    messages.append("Dropped legacy 'kern' table")
                    changed = True
                except Exception:
                    messages.append("Failed to drop 'kern' table")
        else:
            messages.append("No legacy 'kern' data found")

    if do_liga:
        if ligs_resolved:
            fea = build_liga_feature_text(font, ligs_resolved)
            ok, msg = apply_feature_text(font, fea)
            if ok:
                messages.append(
                    f"Added {len(ligs_resolved)} ligatures to GSUB liga feature"
                )
            else:
                messages.append(f"Ligature addition failed: {msg}")
            changed = changed or ok
        else:
            messages.append("No ligatures inferred from names")

    if do_gdef_classes or do_lig_carets:
        ok, msg = build_enriched_gdef(
            font,
            use_classes=do_gdef_classes,
            add_carets=do_lig_carets,
            ligs=ligs_resolved,
        )
        messages.append(msg)
        changed = changed or ok

    return changed, messages
