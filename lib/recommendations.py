"""Graded connect recommendations from glyph detection vs installed features."""

from __future__ import annotations

from typing import Dict, List, Set, Tuple

from .policy_data import installed_conflict_for
from .models import (
    ConnectTier,
    FeatureRecommendation,
    FeatureState,
    FeatureStatus,
    FontFeatureAudit,
    RecommendTier,
)

HIGH_PRIORITY_TAGS = frozenset(
    {
        "liga",
        "dlig",
        "smcp",
        "c2sc",
        "frac",
        "onum",
        "lnum",
        "tnum",
        "pnum",
        "sups",
        "subs",
        "zero",
        "numr",
        "dnom",
        "sinf",
        "ordn",
    }
)

LOW_PRIORITY_TAGS = frozenset({"hist", "titl", "swsh", "calt", "salt"})

# When detected glyphs are wired under these sibling tags, skip reconnect for the key.
LIGATURE_COVERED_BY: Dict[str, frozenset[str]] = {
    "liga": frozenset({"rlig", "clig", "hlig"}),
    "dlig": frozenset({"liga", "rlig"}),
}


def _alternate_coverage_tags(audit: FontFeatureAudit) -> Set[str]:
    """Features that already imply alternate-glyph coverage."""
    covered: Set[str] = set()
    for tag in ("swsh", "calt", "titl", "hist"):
        status = audit.features.get(tag)
        if status and status.state != FeatureState.ABSENT:
            covered.add(tag)
    for tag, status in audit.stylistic_sets.items():
        if status.state != FeatureState.ABSENT:
            covered.add(tag)
    return covered


def _missing_count(status: FeatureStatus) -> int:
    return len(status.missing_pairs) + len(status.missing_ligatures)


def _covered_by_sibling_tag(tag: str, audit: FontFeatureAudit) -> str | None:
    siblings = LIGATURE_COVERED_BY.get(tag)
    if not siblings:
        return None
    present = siblings & audit.gsub_tags
    if not present:
        return None
    detail = next(
        (audit.installed_features[t] for t in sorted(present) if t in audit.installed_features),
        None,
    )
    if detail and detail.populated:
        return detail.tag
    return None


def tier_for_gap(
    tag: str,
    status: FeatureStatus,
    audit: FontFeatureAudit,
) -> Tuple[RecommendTier, str]:
    if status.state in (FeatureState.ABSENT, FeatureState.ACTIVE):
        return RecommendTier.SKIP, ""

    conflict = installed_conflict_for(
        tag,
        audit.gsub_tags,
        installed_features=audit.installed_features,
    )
    if conflict:
        return (
            RecommendTier.SKIP,
            f"conflicts with installed {conflict}",
        )

    if _missing_count(status) == 0:
        sibling = _covered_by_sibling_tag(tag, audit)
        if sibling:
            return RecommendTier.SKIP, f"glyphs wired under {sibling}"
        return RecommendTier.SKIP, "already wired in GSUB"

    if status.connect_tier == ConnectTier.CONTEXTUAL:
        return RecommendTier.MANUAL, "contextual rules need manual review"

    if tag == "salt":
        alt_tags = _alternate_coverage_tags(audit)
        if alt_tags:
            joined = ", ".join(sorted(alt_tags))
            return (
                RecommendTier.SKIP,
                f"alternates likely covered by {joined}",
            )
        return RecommendTier.LOW, "generic stylistic alternate — confirm before wiring"

    if tag.startswith("ss"):
        if status.state == FeatureState.PARTIAL:
            return RecommendTier.MEDIUM, "complete partial stylistic set"
        return RecommendTier.MEDIUM, "wire detected stylistic set glyphs"

    if tag in HIGH_PRIORITY_TAGS:
        return RecommendTier.HIGH, f"{status.label} glyphs detected, feature unwired"

    if tag in LOW_PRIORITY_TAGS:
        return RecommendTier.LOW, f"{status.label} — optional stylistic wiring"

    return RecommendTier.MEDIUM, f"{status.label} glyphs detected, feature unwired"


def compute_recommendations(audit: FontFeatureAudit) -> List[FeatureRecommendation]:
    """Build graded recommendations for gaps worth human or connect attention."""
    recs: List[FeatureRecommendation] = []

    all_statuses: Dict[str, FeatureStatus] = dict(audit.features)
    all_statuses.update(audit.stylistic_sets)

    for tag, status in sorted(all_statuses.items()):
        if not status.has_gaps:
            continue
        tier, reason = tier_for_gap(tag, status, audit)
        if tier == RecommendTier.SKIP:
            continue
        recs.append(
            FeatureRecommendation(
                tag=tag,
                label=status.label,
                tier=tier,
                reason=reason,
                state=status.state,
                missing_count=_missing_count(status),
            )
        )

    tier_order = {
        RecommendTier.HIGH: 0,
        RecommendTier.MEDIUM: 1,
        RecommendTier.LOW: 2,
        RecommendTier.MANUAL: 3,
    }
    recs.sort(key=lambda r: (tier_order[r.tier], r.tag))
    return recs


def connect_allowed(
    tier: RecommendTier,
    *,
    include_low: bool = False,
    include_manual: bool = False,
) -> bool:
    """Tiers that ``connect`` may include in a plan."""
    if tier in (RecommendTier.HIGH, RecommendTier.MEDIUM):
        return True
    if tier == RecommendTier.LOW and include_low:
        return True
    if tier == RecommendTier.MANUAL and include_manual:
        return True
    return False
