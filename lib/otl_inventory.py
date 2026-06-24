"""Installed OpenType feature inventory (tags, lookup depth, policy coverage)."""

from __future__ import annotations

import re
from typing import Dict, List

from fontTools.ttLib import TTFont

from .feature_policy import naming_policy_tags
from .models import InstalledFeatureDetail

_SS_TAG = re.compile(r"^ss(0[1-9]|1[0-9]|20)$")


def tag_in_naming_policy(tag: str) -> bool:
    if tag in naming_policy_tags():
        return True
    return bool(_SS_TAG.match(tag))


def _lookup_has_rules(lookup) -> bool:
    lookup_type = lookup.LookupType
    subtables = getattr(lookup, "SubTable", None) or []

    if lookup_type == 1:
        for subtable in subtables:
            mapping = getattr(subtable, "mapping", None)
            if mapping:
                return True
        return False

    if lookup_type == 4:
        for subtable in subtables:
            ligatures = getattr(subtable, "ligatures", None)
            if not ligatures:
                continue
            for lig_list in ligatures.values():
                if lig_list:
                    return True
        return False

    if lookup_type in (2, 3, 5, 6, 7, 8):
        return bool(subtables)

    if lookup_type == 9:
        for subtable in subtables:
            if getattr(subtable, "SubstLookupRecord", None):
                return True
        return False

    return bool(subtables)


def _gpos_lookup_has_rules(lookup) -> bool:
    lookup_type = lookup.LookupType
    subtables = getattr(lookup, "SubTable", None) or []

    if lookup_type == 1:
        for subtable in subtables:
            if getattr(subtable, "PairSets", None):
                return True
            if getattr(subtable, "PairSetCount", 0):
                return True
        return False

    if lookup_type == 2:
        for subtable in subtables:
            if getattr(subtable, "Value", None) is not None:
                return True
            if getattr(subtable, "Pos", None) is not None:
                return True
        return bool(subtables)

    if lookup_type in (3, 4, 5, 6, 7, 8, 9):
        return bool(subtables)

    return bool(subtables)


def analyze_installed_features(font: TTFont) -> Dict[str, InstalledFeatureDetail]:
    """Map feature tag → install detail for GSUB and GPOS."""
    details: Dict[str, InstalledFeatureDetail] = {}

    for table_tag, rule_checker in (
        ("GSUB", _lookup_has_rules),
        ("GPOS", _gpos_lookup_has_rules),
    ):
        if table_tag not in font:
            continue
        table = font[table_tag].table
        if not hasattr(table, "FeatureList") or not table.FeatureList:
            continue
        lookup_list = table.LookupList if hasattr(table, "LookupList") else None
        lookups = lookup_list.Lookup if lookup_list and lookup_list.Lookup else []

        for frec in table.FeatureList.FeatureRecord:
            tag = frec.FeatureTag
            indices = list(frec.Feature.LookupListIndex or [])
            populated = False
            for idx in indices:
                if 0 <= idx < len(lookups) and rule_checker(lookups[idx]):
                    populated = True
                    break
            details[tag] = InstalledFeatureDetail(
                tag=tag,
                table=table_tag,
                lookup_count=len(indices),
                populated=populated,
                in_naming_policy=tag_in_naming_policy(tag),
            )

    return details


def tags_beyond_naming_policy(
    installed: Dict[str, InstalledFeatureDetail],
) -> List[InstalledFeatureDetail]:
    """Installed features not covered by glyph-naming policy scan."""
    return sorted(
        (d for d in installed.values() if not d.in_naming_policy),
        key=lambda d: (d.table, d.tag),
    )


def empty_installed_tags(
    installed: Dict[str, InstalledFeatureDetail],
) -> List[str]:
    """Feature records present but with no populated lookups."""
    return sorted(
        d.tag for d in installed.values() if d.lookup_count == 0 or not d.populated
    )
