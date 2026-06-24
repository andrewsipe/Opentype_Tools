"""Build and apply GSUB ``aalt`` (Access All Alternates) from installed features."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from fontTools.otlLib.builder import AlternateSubstBuilder
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables import otTables

from .coverage import sort_coverage_tables_in_font
from .feature_policy import aalt_source_tags
from .gsub_merge import (
    _append_lookup,
    _ensure_default_script,
    _ensure_gsub_table,
    _find_feature_index,
    _register_feature_in_scripts,
)
from .otl_inventory import analyze_installed_features
from .wrapper_helpers import ensure_otl_scaffolding

_SUPPORTED_SOURCE_LOOKUP_TYPES = frozenset({1, 4})


@dataclass
class AaltPlan:
    source_tags: List[str] = field(default_factory=list)
    fea_content: str = ""
    needs_update: bool = False
    skip_reason: str = ""
    blocked: bool = False
    block_reason: str = ""


def generate_aalt_fea(
    alternates: Dict[str, List[str]],
    *,
    ligature_tags: List[str] | None = None,
) -> str:
    """Build FEA for ``aalt`` from explicit alternate sets."""
    if not alternates and not ligature_tags:
        return ""
    lines = ["feature aalt {"]
    if ligature_tags:
        lines.append(
            "  # Ligature lookups included: " + ", ".join(ligature_tags)
        )
    for base in sorted(alternates):
        alts = alternates[base]
        if len(alts) < 2:
            continue
        lines.append(f"  sub {base} from [{' '.join(alts)}];")
    lines.append("} aalt;")
    return "\n".join(lines)


def _source_has_unsupported_lookups(gsub: otTables.GSUB, source_tags: List[str]) -> bool:
    for tag in source_tags:
        feat_idx = _find_feature_index(gsub, tag)
        if feat_idx is None:
            continue
        frec = gsub.FeatureList.FeatureRecord[feat_idx]
        for li in frec.Feature.LookupListIndex or []:
            lookup = gsub.LookupList.Lookup[li]
            if lookup.LookupType not in _SUPPORTED_SOURCE_LOOKUP_TYPES:
                return True
    return False


def _collect_alternates_and_ligatures(
    gsub: otTables.GSUB,
    source_tags: List[str],
) -> Tuple[OrderedDict[str, List[str]], List[int], List[str]]:
    alternates: OrderedDict[str, List[str]] = OrderedDict()
    lig_lookup_indices: List[int] = []
    ligature_tags: List[str] = []

    for tag in source_tags:
        feat_idx = _find_feature_index(gsub, tag)
        if feat_idx is None:
            continue
        frec = gsub.FeatureList.FeatureRecord[feat_idx]
        tag_has_liga = False
        for li in frec.Feature.LookupListIndex or []:
            lookup = gsub.LookupList.Lookup[li]
            if lookup.LookupType == 1:
                for subtable in lookup.SubTable:
                    mapping = getattr(subtable, "mapping", None)
                    if not mapping:
                        continue
                    for inp, out in mapping.items():
                        bucket = alternates.setdefault(inp, [])
                        if inp not in bucket:
                            bucket.append(inp)
                        if out not in bucket:
                            bucket.append(out)
            elif lookup.LookupType == 4:
                tag_has_liga = True
                if li not in lig_lookup_indices:
                    lig_lookup_indices.append(li)
        if tag_has_liga:
            ligature_tags.append(tag)

    return alternates, lig_lookup_indices, ligature_tags


def build_aalt_plan(font: TTFont, *, force: bool = False) -> AaltPlan:
    """Plan ``aalt`` generation for a font without mutating it."""
    plan = AaltPlan()
    installed = analyze_installed_features(font)
    plan.source_tags = aalt_source_tags(installed)

    if not plan.source_tags:
        plan.skip_reason = "No populated GSUB features to index"
        return plan

    if "GSUB" not in font:
        plan.skip_reason = "No GSUB table"
        return plan

    gsub = font["GSUB"].table
    if _source_has_unsupported_lookups(gsub, plan.source_tags) and not force:
        plan.blocked = True
        plan.block_reason = (
            "Source feature uses lookup types beyond simple/ligature substitution; "
            "use --force to build aalt from extractable rules only"
        )
        return plan

    alternates, lig_lookup_indices, ligature_tags = _collect_alternates_and_ligatures(
        gsub, plan.source_tags
    )
    if not alternates and not lig_lookup_indices:
        plan.skip_reason = "No extractable alternates or ligatures in source features"
        return plan

    plan.fea_content = generate_aalt_fea(alternates, ligature_tags=ligature_tags)

    aalt_detail = installed.get("aalt")
    if aalt_detail and aalt_detail.populated and not force:
        plan.skip_reason = "aalt already populated (use --force to replace)"
        return plan

    plan.needs_update = True
    return plan


def _attach_or_replace_aalt_feature(
    gsub: otTables.GSUB,
    lookup_indices: List[int],
) -> None:
    feat_idx = _find_feature_index(gsub, "aalt")
    if feat_idx is None:
        frec = otTables.FeatureRecord()
        frec.FeatureTag = "aalt"
        frec.Feature = otTables.Feature()
        frec.Feature.LookupListIndex = lookup_indices
        frec.Feature.LookupCount = len(lookup_indices)
        gsub.FeatureList.FeatureRecord.append(frec)
        feat_idx = len(gsub.FeatureList.FeatureRecord) - 1
        gsub.FeatureList.FeatureCount = len(gsub.FeatureList.FeatureRecord)
        _register_feature_in_scripts(gsub, feat_idx)
        return

    frec = gsub.FeatureList.FeatureRecord[feat_idx]
    frec.Feature.LookupListIndex = lookup_indices
    frec.Feature.LookupCount = len(lookup_indices)
    _ensure_default_script(gsub)
    _register_feature_in_scripts(gsub, feat_idx)


def apply_aalt_to_font(
    font: TTFont,
    *,
    force: bool = False,
) -> Tuple[bool, List[str]]:
    """Attach ``aalt`` referencing alternates and ligature lookups from source features."""
    messages: List[str] = []
    plan = build_aalt_plan(font, force=force)

    if plan.blocked:
        return False, [plan.block_reason]
    if not plan.needs_update:
        return False, [plan.skip_reason or "No aalt changes needed"]

    gsub = _ensure_gsub_table(font)
    alternates, lig_lookup_indices, ligature_tags = _collect_alternates_and_ligatures(
        gsub, plan.source_tags
    )

    lookup_indices = list(lig_lookup_indices)
    if alternates:
        builder = AlternateSubstBuilder(font, "aalt")
        builder.alternates = {
            base: alts for base, alts in alternates.items() if len(alts) >= 2
        }
        if builder.alternates:
            alt_lookup = builder.build()
            lookup_indices.insert(0, _append_lookup(gsub, alt_lookup))

    if not lookup_indices:
        return False, ["No aalt lookups to attach"]

    _attach_or_replace_aalt_feature(gsub, lookup_indices)
    messages.extend(ensure_otl_scaffolding(font))
    sort_coverage_tables_in_font(font, verbose=False)
    parts = [f"Built aalt referencing {len(plan.source_tags)} feature(s)"]
    if ligature_tags:
        parts.append(f"ligatures: {', '.join(ligature_tags)}")
    if alternates:
        parts.append(f"{sum(1 for a in alternates.values() if len(a) >= 2)} alternate set(s)")
    messages.append(" — ".join(parts))
    return True, messages


def gsub_has_unsupported_lookups(font: TTFont) -> bool:
    """True when any GSUB lookup type is outside simple/ligature substitution."""
    if "GSUB" not in font:
        return False
    gsub = font["GSUB"].table
    if not gsub.LookupList or not gsub.LookupList.Lookup:
        return False
    for lookup in gsub.LookupList.Lookup:
        if lookup.LookupType not in _SUPPORTED_SOURCE_LOOKUP_TYPES:
            return True
    return False
