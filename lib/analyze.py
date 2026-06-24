"""Build structured FontFeatureAudit from font analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Set, Tuple

from fontTools.ttLib import TTFont

from .detection import UnifiedGlyphDetector
from .feature_extraction import ExistingSubstitutionExtractor, FeatureExtractor
from .feature_policy import (
    FRAC_FEATURE,
    LIGATURE_FEATURES,
    SINGLE_FEATURES,
    detect_frac_parts,
    detect_single_pairs,
    policy_by_tag,
)
from .models import (
    ConnectTier,
    FeatureState,
    FeatureStatus,
    FontFeatureAudit,
    GlyphInventory,
    WrapStatus,
)
from .otl_inventory import analyze_installed_features
from .policy_data import feature_label
from .recommendations import compute_recommendations
from .validation import FontValidator
from .wrap_assess import assess_wrap_status


def get_existing_feature_tags(font: TTFont) -> Tuple[Set[str], Set[str], Set[str]]:
    """Return (all tags, GSUB tags, GPOS tags)."""
    gsub_tags: Set[str] = set()
    gpos_tags: Set[str] = set()
    if "GSUB" in font:
        table = font["GSUB"].table
        if hasattr(table, "FeatureList") and table.FeatureList:
            for frec in table.FeatureList.FeatureRecord:
                gsub_tags.add(frec.FeatureTag)
    if "GPOS" in font:
        table = font["GPOS"].table
        if hasattr(table, "FeatureList") and table.FeatureList:
            for frec in table.FeatureList.FeatureRecord:
                gpos_tags.add(frec.FeatureTag)
    return gsub_tags | gpos_tags, gsub_tags, gpos_tags


def _has_detected_feature_glyphs(features: Dict[str, FeatureStatus], stylistic_sets: Dict[str, FeatureStatus]) -> bool:
    for status in list(features.values()) + list(stylistic_sets.values()):
        if status.state in (FeatureState.INACTIVE, FeatureState.PARTIAL):
            return True
    return False


def _otl_stripped_suspected(
    validator: FontValidator,
    features: Dict[str, FeatureStatus],
    stylistic_sets: Dict[str, FeatureStatus],
) -> bool:
    if not _has_detected_feature_glyphs(features, stylistic_sets):
        return False
    state = validator.state
    return not state.has_gsub


def _classify_single(
    tag: str,
    label: str,
    tier: ConnectTier,
    detected: List[Tuple[str, str]],
    wired: Set[Tuple[str, str]],
    tag_present: bool,
) -> FeatureStatus:
    wired_pairs = [p for p in detected if p in wired]
    missing_pairs = [p for p in detected if p not in wired]

    if not detected:
        state = FeatureState.ABSENT
    elif not missing_pairs:
        state = FeatureState.ACTIVE
    elif not tag_present:
        state = FeatureState.INACTIVE
    else:
        state = FeatureState.PARTIAL

    return FeatureStatus(
        tag=tag,
        label=label,
        state=state,
        connect_tier=tier,
        detected_pairs=detected,
        wired_pairs=wired_pairs,
        missing_pairs=missing_pairs,
    )


def _classify_ligature(
    tag: str,
    label: str,
    ligatures: List[Tuple[List[str], str]],
    wired_ligs: Set[Tuple[str, ...]],
    tag_present: bool,
) -> FeatureStatus:
    missing = []
    wired_list = []
    for components, lig_glyph in ligatures:
        key = tuple(components)
        if key in wired_ligs:
            wired_list.append((key, lig_glyph))
        else:
            missing.append((key, lig_glyph))

    if not ligatures:
        state = FeatureState.ABSENT
    elif not missing:
        state = FeatureState.ACTIVE
    elif not tag_present:
        state = FeatureState.INACTIVE
    else:
        state = FeatureState.PARTIAL

    return FeatureStatus(
        tag=tag,
        label=label,
        state=state,
        connect_tier=ConnectTier.LIGATURE,
        ligatures=[(tuple(c), g) for c, g in ligatures],
        missing_ligatures=missing,
    )


def _classify_frac(
    numerators: List[Tuple[str, str]],
    denominators: List[Tuple[str, str]],
    wired: Set[Tuple[str, str]],
    tag_present: bool,
) -> FeatureStatus:
    all_pairs = numerators + denominators
    wired_pairs = [p for p in all_pairs if p in wired]
    missing_pairs = [p for p in all_pairs if p not in wired]

    if not all_pairs:
        state = FeatureState.ABSENT
    elif not missing_pairs:
        state = FeatureState.ACTIVE
    elif not tag_present:
        state = FeatureState.INACTIVE
    else:
        state = FeatureState.PARTIAL

    return FeatureStatus(
        tag=FRAC_FEATURE.tag,
        label=FRAC_FEATURE.label,
        state=state,
        connect_tier=ConnectTier.CONTEXTUAL,
        frac_numerators=numerators,
        frac_denominators=denominators,
        detected_pairs=all_pairs,
        wired_pairs=wired_pairs,
        missing_pairs=missing_pairs,
    )


def _classify_stylistic_set(
    ss_num: int,
    substitutions: List[Tuple[str, str]],
    wired: Set[Tuple[str, str]],
    tag_present: bool,
) -> FeatureStatus:
    tag = f"ss{ss_num:02d}"
    wired_pairs = [p for p in substitutions if p in wired]
    missing_pairs = [p for p in substitutions if p not in wired]

    if not substitutions:
        state = FeatureState.ABSENT
    elif not missing_pairs:
        state = FeatureState.ACTIVE
    elif not tag_present:
        state = FeatureState.INACTIVE
    else:
        state = FeatureState.PARTIAL

    return FeatureStatus(
        tag=tag,
        label=feature_label(f"ss{ss_num:02d}"),
        state=state,
        connect_tier=ConnectTier.SIMPLE,
        detected_pairs=substitutions,
        wired_pairs=wired_pairs,
        missing_pairs=missing_pairs,
    )


def analyze_font(font: TTFont, path: Path) -> FontFeatureAudit:
    """Produce structured audit for one font."""
    detector = UnifiedGlyphDetector(font)
    extractor = FeatureExtractor(font)
    existing_extractor = ExistingSubstitutionExtractor(font)
    validator = FontValidator(font)

    existing_tags, gsub_tags, gpos_tags = get_existing_feature_tags(font)
    installed_features = analyze_installed_features(font)
    existing_subs = existing_extractor.extract_all()
    wired_singles: Set[Tuple[str, str]] = existing_subs["single"]
    wired_ligs: Set[Tuple[str, ...]] = existing_subs["ligatures"]

    classifications = detector.classify_all_glyphs()
    detected = detector.get_features()
    glyph_order = set(font.getGlyphOrder())
    try:
        unicode_mapped = len(font.getBestCmap() or {})
    except Exception:
        unicode_mapped = 0
    glyph_inventory = GlyphInventory(
        glyph_count=len(glyph_order),
        variant_glyph_count=sum(
            1 for c in classifications.values() if c.is_feature_glyph()
        ),
        unicode_mapped_count=unicode_mapped,
    )

    features: Dict[str, FeatureStatus] = {}

    for entry in SINGLE_FEATURES:
        if entry.patterns:
            pairs = detect_single_pairs(glyph_order, entry.patterns)
        else:
            pairs = detected.get(entry.tag, [])
        features[entry.tag] = _classify_single(
            entry.tag,
            entry.label,
            entry.connect_tier,
            pairs,
            wired_singles,
            entry.tag in existing_tags,
        )

    for entry in LIGATURE_FEATURES:
        ligs = detected.get(entry.tag, [])
        features[entry.tag] = _classify_ligature(
            entry.tag,
            entry.label,
            ligs,
            wired_ligs,
            entry.tag in existing_tags,
        )

    nums, denoms = detect_frac_parts(glyph_order, FRAC_FEATURE.patterns)
    features[FRAC_FEATURE.tag] = _classify_frac(
        nums, denoms, wired_singles, FRAC_FEATURE.tag in existing_tags
    )

    stylistic_sets: Dict[str, FeatureStatus] = {}
    for ss_num, subs in sorted(detected.get("stylistic_sets", {}).items()):
        if 1 <= ss_num <= 20:
            tag = f"ss{ss_num:02d}"
            stylistic_sets[tag] = _classify_stylistic_set(
                ss_num, subs, wired_singles, tag in existing_tags
            )

    wrap_status = assess_wrap_status(font)
    otl_stripped = _otl_stripped_suspected(validator, features, stylistic_sets)
    if otl_stripped and wrap_status.reason:
        wrap_status = WrapStatus(
            needs_scaffolding=wrap_status.needs_scaffolding,
            can_wrap=wrap_status.can_wrap,
            reason=wrap_status.reason + "; glyph-rich but OTL empty (likely stripped or omitted)",
            outline_kind=wrap_status.outline_kind,
            wrap_plan_summary=wrap_status.wrap_plan_summary,
        )

    warnings: List[str] = []
    if wrap_status.flagged_unsupported:
        warnings.append(wrap_status.reason)
    if otl_stripped:
        warnings.append(
            "Feature glyphs detected but OpenType layout is empty — run wrap before connect"
        )
    if not glyph_inventory.has_variant_glyphs:
        if glyph_inventory.limited_glyph_set:
            warnings.append(
                f"Small glyph set ({glyph_inventory.glyph_count} glyphs, no variant "
                "suffixes) — likely trial/subset; reconnect scope is very limited"
            )
        else:
            warnings.append(
                "No variant glyphs detected by naming patterns — connect has little to wire"
            )

    audit = FontFeatureAudit(
        path=path.resolve(),
        existing_tags=existing_tags,
        gsub_tags=gsub_tags,
        gpos_tags=gpos_tags,
        installed_features=installed_features,
        features=features,
        stylistic_sets=stylistic_sets,
        wrap_status=wrap_status,
        glyph_inventory=glyph_inventory,
        otl_stripped_suspected=otl_stripped,
        has_gsub_table=validator.state.has_gsub,
        active_fea=extractor.extract_all_features_as_fea(),
        warnings=warnings,
    )
    audit.recommendations = compute_recommendations(audit)
    return audit


def policy_for_tag(tag: str):
    return policy_by_tag().get(tag)
