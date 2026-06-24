"""Apply FEA feature code to fonts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import otTables

from .gsub_merge import merge_gsub_from_fea
from .wrapper_helpers import empty_otl_table

try:
    from fontTools.feaLib.builder import addOpenTypeFeaturesFromString

    HAVE_FEALIB = True
except Exception:
    HAVE_FEALIB = False
    addOpenTypeFeaturesFromString = None


def parse_fea_file(fea_path: Path) -> str:
    with open(fea_path, "r", encoding="utf-8") as f:
        return f.read()


def detect_feature_conflicts(font: TTFont, fea_content: str) -> List[str]:
    warnings: List[str] = []
    fea_tags = set(re.findall(r"feature\s+(\w+)\s*\{", fea_content))
    existing_tags = set()
    for table_tag in ("GSUB", "GPOS"):
        if table_tag not in font:
            continue
        table = font[table_tag].table
        if hasattr(table, "FeatureList") and table.FeatureList:
            for frec in table.FeatureList.FeatureRecord:
                existing_tags.add(frec.FeatureTag)
    conflicts = fea_tags.intersection(existing_tags)
    if conflicts:
        warnings.append(
            f"Features already in font: {', '.join(sorted(conflicts))}. "
            "Merge mode will append new lookups only (existing lookups preserved)."
        )
    return warnings


def apply_features_to_font(
    font: TTFont,
    fea_content: str,
    *,
    replace_mode: bool = False,
    merge_mode: bool = True,
) -> tuple[bool, list[str]]:
    """
    Apply FEA content to a font.

    Default ``merge_mode`` appends simple GSUB rules without replacing the table.
    ``replace_mode`` clears GSUB/GPOS then compiles FEA (destructive; use with care).
    fontTools ``addOpenTypeFeaturesFromString`` always replaces targeted tables.
    """
    messages: List[str] = []
    if not HAVE_FEALIB:
        return False, ["fontTools.feaLib is required but not available"]

    if "GDEF" not in font:
        gdef = newTable("GDEF")
        gdef.table = otTables.GDEF()
        gdef.table.Version = 0x00010000
        gdef.table.GlyphClassDef = None
        gdef.table.AttachList = None
        gdef.table.LigCaretList = None
        gdef.table.MarkAttachClassDef = None
        gdef.table.MarkGlyphSetsDef = None
        font["GDEF"] = gdef
        messages.append("Created GDEF table (required for features)")

    if replace_mode:
        for otl_tag, ot_cls in (("GSUB", otTables.GSUB), ("GPOS", otTables.GPOS)):
            if otl_tag not in font:
                continue
            otl = font[otl_tag].table
            if hasattr(otl, "LookupList") and otl.LookupList:
                lookup_count = len(otl.LookupList.Lookup)
                if lookup_count > 0:
                    new_table = newTable(otl_tag)
                    new_table.table = empty_otl_table(ot_cls)
                    font[otl_tag] = new_table
                    messages.append(f"Cleared {otl_tag} ({lookup_count} lookups removed)")

        try:
            addOpenTypeFeaturesFromString(font, fea_content)
            messages.append("Features compiled and applied (replace mode)")
            return True, messages
        except Exception as e:
            return False, [f"Failed to compile features: {e}"]

    if merge_mode:
        ok, merge_messages = merge_gsub_from_fea(font, fea_content)
        messages.extend(merge_messages)
        return ok, messages

    try:
        addOpenTypeFeaturesFromString(font, fea_content, tables=["GSUB"])
        messages.append(
            "Features compiled and applied (GSUB table replaced — prefer merge mode)"
        )
        return True, messages
    except Exception as e:
        return False, [f"Failed to compile features: {e}"]
