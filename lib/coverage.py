"""
Coverage table sorting for OpenType fonts.

Sorts Coverage tables by GlyphID to match GlyphOrder, which is required
by some font processors and prevents validation warnings.

Uses direct fontTools API manipulation instead of TTX conversion for reliability.
"""

from pathlib import Path
from typing import Tuple

from fontTools.ttLib import TTFont

from .fontcore_path import ensure_fontcore_on_path

ensure_fontcore_on_path(Path(__file__).resolve().parent.parent)

from FontCore.core_gpos_repair import (  # noqa: E402
    get_glyph_id,
    iter_expand_subtables,
    repair_pairpos_second_glyph_order,
)
import FontCore.core_console_styles as cs  # noqa: E402


def sort_coverage(font: TTFont, coverage) -> bool:
    """
    Sort a Coverage table by glyph IDs.

    Returns:
        True if sorting was needed (order changed), False otherwise
    """
    if not hasattr(coverage, "glyphs") or not coverage.glyphs:
        return False

    # Get current order
    old_glyphs = list(coverage.glyphs)

    # Get glyph IDs and sort
    glyph_data = [(get_glyph_id(font, g), g) for g in coverage.glyphs]
    glyph_data.sort(key=lambda x: x[0])
    coverage.glyphs = [g for _, g in glyph_data]

    # Check if order changed
    return old_glyphs != coverage.glyphs


def sort_class_def(font: TTFont, class_def) -> bool:
    """
    Sort a ClassDef table by glyph IDs.

    Returns:
        True if sorting was needed, False otherwise
    """
    if not hasattr(class_def, "classDefs") or not class_def.classDefs:
        return False

    # ClassDef is a dict, just ensure it's ordered by glyph ID
    old_items = list(class_def.classDefs.items())
    sorted_items = sorted(
        class_def.classDefs.items(), key=lambda x: get_glyph_id(font, x[0])
    )
    class_def.classDefs = dict(sorted_items)

    # Check if order changed (dict order matters in Python 3.7+)
    return old_items != sorted_items


def process_lookup(font: TTFont, lookup) -> int:
    """
    Process a single lookup and sort all its Coverage tables.

    Returns:
        Number of coverage tables sorted
    """
    sorted_count = 0

    if not hasattr(lookup, "SubTable"):
        return sorted_count

    for subtable in iter_expand_subtables(lookup.SubTable):
        cov = getattr(subtable, "Coverage", None)
        pair_sets = getattr(subtable, "PairSet", None)
        lig_keys = getattr(subtable, "ligatures", None)

        # PairPos / LigSubst: capture pre-sort glyph order once, sort once, remap parallel arrays / dict keys
        if (
            cov is not None
            and hasattr(cov, "glyphs")
            and cov.glyphs
            and pair_sets is not None
        ):
            try:
                old_glyphs = list(cov.glyphs)
                if sort_coverage(font, cov):
                    sorted_count += 1
                new_glyphs = cov.glyphs
                old_to_new = {}
                for old_idx, glyph in enumerate(old_glyphs):
                    if glyph in new_glyphs:
                        new_idx = new_glyphs.index(glyph)
                        old_to_new[old_idx] = new_idx
                if (
                    pair_sets
                    and len(old_to_new) == len(old_glyphs)
                    and len(old_to_new) == len(new_glyphs)
                ):
                    old_pairset = subtable.PairSet[:]
                    new_pairset = [None] * len(old_pairset)
                    for old_idx, new_idx in old_to_new.items():
                        if old_idx < len(old_pairset):
                            new_pairset[new_idx] = old_pairset[old_idx]
                    if None not in new_pairset:
                        subtable.PairSet = new_pairset
            except (AttributeError, TypeError, ValueError):
                pass
        elif (
            cov is not None and hasattr(cov, "glyphs") and cov.glyphs and lig_keys is not None
        ):
            try:
                old_glyphs = list(cov.glyphs)
                if sort_coverage(font, cov):
                    sorted_count += 1
                new_glyphs = cov.glyphs
                old_ligatures = subtable.ligatures.copy()
                new_ligatures = {}
                for glyph in new_glyphs:
                    if glyph in old_ligatures:
                        new_ligatures[glyph] = old_ligatures[glyph]
                subtable.ligatures = new_ligatures
            except (AttributeError, TypeError):
                pass
        elif cov is not None:
            if sort_coverage(font, cov):
                sorted_count += 1

        if hasattr(subtable, "ClassDef"):
            sort_class_def(font, subtable.ClassDef)

        if hasattr(subtable, "BacktrackCoverage"):
            for c in subtable.BacktrackCoverage:
                if sort_coverage(font, c):
                    sorted_count += 1

        if hasattr(subtable, "InputCoverage"):
            for c in subtable.InputCoverage:
                if sort_coverage(font, c):
                    sorted_count += 1

        if hasattr(subtable, "LookAheadCoverage"):
            for c in subtable.LookAheadCoverage:
                if sort_coverage(font, c):
                    sorted_count += 1

    return sorted_count


def process_table(font: TTFont, table_tag: str) -> Tuple[int, int]:
    """
    Process GSUB or GPOS table.

    Returns:
        (total_coverage, sorted_count) tuple
    """
    total_coverage = 0
    sorted_count = 0

    if table_tag not in font:
        return total_coverage, sorted_count

    table = font[table_tag]

    if hasattr(table, "table"):
        table = table.table

    # Process all lookup lists
    if hasattr(table, "LookupList") and table.LookupList:
        for lookup in table.LookupList.Lookup:
            # Count coverage tables in this lookup
            if hasattr(lookup, "SubTable"):
                for subtable in lookup.SubTable:
                    # Count main Coverage
                    if hasattr(subtable, "Coverage") and hasattr(
                        subtable.Coverage, "glyphs"
                    ):
                        if subtable.Coverage.glyphs:
                            total_coverage += 1

                    # Count contextual coverage
                    if hasattr(subtable, "BacktrackCoverage"):
                        total_coverage += len(subtable.BacktrackCoverage)
                    if hasattr(subtable, "InputCoverage"):
                        total_coverage += len(subtable.InputCoverage)
                    if hasattr(subtable, "LookAheadCoverage"):
                        total_coverage += len(subtable.LookAheadCoverage)

            # Sort coverage in this lookup
            sorted_count += process_lookup(font, lookup)

    return total_coverage, sorted_count


def process_gdef(font: TTFont) -> Tuple[int, int]:
    """
    Process GDEF table.

    Returns:
        (total_coverage, sorted_count) tuple
    """
    total_coverage = 0
    sorted_count = 0

    if "GDEF" not in font:
        return total_coverage, sorted_count

    gdef = font["GDEF"].table

    # Sort LigCaretList Coverage
    if hasattr(gdef, "LigCaretList") and gdef.LigCaretList:
        lig_caret = gdef.LigCaretList
        if hasattr(lig_caret, "Coverage") and hasattr(lig_caret.Coverage, "glyphs"):
            if lig_caret.Coverage.glyphs:
                total_coverage += 1
                old_glyphs = list(lig_caret.Coverage.glyphs)
                if sort_coverage(font, lig_caret.Coverage):
                    sorted_count += 1
                new_glyphs = lig_caret.Coverage.glyphs

                # Reorder LigGlyph array to match sorted Coverage
                if hasattr(lig_caret, "LigGlyph") and lig_caret.LigGlyph and old_glyphs:
                    old_lig_glyphs = lig_caret.LigGlyph[:]
                    new_lig_glyphs = [None] * len(old_lig_glyphs)

                    for i, old_glyph in enumerate(old_glyphs):
                        if old_glyph in new_glyphs and i < len(old_lig_glyphs):
                            new_idx = new_glyphs.index(old_glyph)
                            new_lig_glyphs[new_idx] = old_lig_glyphs[i]

                    # Validate no None values remain before assigning
                    if None in new_lig_glyphs:
                        lig_caret.LigGlyph = [
                            lg for lg in new_lig_glyphs if lg is not None
                        ]
                    else:
                        lig_caret.LigGlyph = new_lig_glyphs

    # Sort AttachList Coverage
    if hasattr(gdef, "AttachList") and gdef.AttachList:
        if hasattr(gdef.AttachList, "Coverage") and hasattr(
            gdef.AttachList.Coverage, "glyphs"
        ):
            if gdef.AttachList.Coverage.glyphs:
                total_coverage += 1
                if sort_coverage(font, gdef.AttachList.Coverage):
                    sorted_count += 1

    # Sort MarkAttachClassDef
    if hasattr(gdef, "MarkAttachClassDef") and gdef.MarkAttachClassDef:
        sort_class_def(font, gdef.MarkAttachClassDef)

    # Sort GlyphClassDef
    if hasattr(gdef, "GlyphClassDef") and gdef.GlyphClassDef:
        sort_class_def(font, gdef.GlyphClassDef)

    return total_coverage, sorted_count


def sort_coverage_tables_in_font(
    font: TTFont, verbose: bool = False
) -> Tuple[int, int]:
    """
    Sort all Coverage tables in a font by glyph ID using direct fontTools API.

    This directly manipulates the font object's Coverage tables, which is more
    reliable than TTX conversion and doesn't require the ttx command-line tool.

    The font object is modified in place.

    Args:
        font: TTFont object (modified in place)
        verbose: Whether to show verbose output

    Returns:
        (total_coverage, sorted_count) tuple
        Returns (0, 0) only when there are genuinely no coverage tables found.
    """
    total_coverage = 0
    sorted_count = 0

    # Process GSUB table
    gsub_total, gsub_sorted = process_table(font, "GSUB")
    total_coverage += gsub_total
    sorted_count += gsub_sorted

    # Process GPOS table
    gpos_total, gpos_sorted = process_table(font, "GPOS")
    total_coverage += gpos_total
    sorted_count += gpos_sorted

    # Process GDEF table
    gdef_total, gdef_sorted = process_gdef(font)
    total_coverage += gdef_total
    sorted_count += gdef_sorted

    pairpos_fixes = repair_pairpos_second_glyph_order(font)
    sorted_count += len(pairpos_fixes)

    if verbose and pairpos_fixes:
        for lookup_index, first_glyph, old_order, new_order in pairpos_fixes:
            cs.StatusIndicator("info").add_message(
                f"GPOS Lookup[{lookup_index}] {first_glyph}: "
                f"reordered pair targets {old_order} -> {new_order}"
            ).emit()

    if verbose and total_coverage > 0:
        cs.StatusIndicator("info").add_message(
            f"Found {total_coverage} Coverage table(s), sorted {sorted_count}"
        ).emit()

    return total_coverage, sorted_count
