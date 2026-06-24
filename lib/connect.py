"""Build and render feature reconnection plans."""

from __future__ import annotations

from typing import Dict, List, Optional

from fontTools.ttLib import TTFont

from .feature_generation import FeatureCodeGenerator
from .feature_policy import (
    FRAC_FEATURE,
    LIGATURE_FEATURES,
    SINGLE_FEATURES,
    generate_feature_fea,
)
from .models import (
    ConnectOptions,
    ConnectPlan,
    ConnectSkippedItem,
    ConnectTier,
    FeatureState,
    FeatureStatus,
    FontFeatureAudit,
    RecommendTier,
)
from .recommendations import connect_allowed

import FontCore.core_console_styles as cs


def connect_block_reason(audit: FontFeatureAudit) -> Optional[str]:
    """Return a user-facing reason when connect should not run, or None if OK."""
    if (
        audit.glyph_inventory.limited_glyph_set
        and not audit.glyph_inventory.has_variant_glyphs
    ):
        return (
            f"Trial/subset glyph set ({audit.glyph_inventory.glyph_count} glyphs) — "
            "nothing to reconnect"
        )
    if not audit.has_gsub_table:
        if audit.wrap_status.can_wrap:
            return "GSUB table missing — run wrap before connect"
        return audit.wrap_status.reason or "Wrap not supported for this font"
    if audit.otl_stripped_suspected:
        return "OpenType layout missing — run wrap before connect"
    return None


def _connectable_tags(audit: FontFeatureAudit, options: ConnectOptions) -> set[str]:
    return {
        r.tag
        for r in audit.recommendations
        if connect_allowed(
            r.tier,
            include_low=options.include_low,
            include_manual=options.include_manual,
        )
    }


def _skipped_from_recommendations(
    audit: FontFeatureAudit, options: ConnectOptions
) -> List[ConnectSkippedItem]:
    skipped: List[ConnectSkippedItem] = []
    for rec in audit.recommendations:
        if connect_allowed(
            rec.tier,
            include_low=options.include_low,
            include_manual=options.include_manual,
        ):
            continue
        skipped.append(
            ConnectSkippedItem(tag=rec.tag, reason=rec.reason, tier=rec.tier.value)
        )

    # Gaps that never became recommendations (e.g. salt skipped entirely in scan).
    rec_tags = {r.tag for r in audit.recommendations}
    for status in audit.gaps():
        if status.tag in rec_tags:
            continue
        if status.state == FeatureState.ABSENT:
            continue
        reason = "not recommended by scan policy"
        if status.tag == "salt":
            reason = "alternates covered by ss/swsh/calt"
        skipped.append(ConnectSkippedItem(tag=status.tag, reason=reason, tier="skip"))
    return skipped


def build_connect_plan(
    audit: FontFeatureAudit,
    options: ConnectOptions | None = None,
) -> ConnectPlan:
    options = options or ConnectOptions()
    block_reason = connect_block_reason(audit)
    if block_reason:
        return ConnectPlan(
            path=audit.path,
            features={},
            stylistic_sets={},
            skipped=_skipped_from_recommendations(audit, options),
            blocked=True,
            block_reason=block_reason,
        )

    features: Dict[str, FeatureStatus] = {}
    stylistic_sets: Dict[str, FeatureStatus] = {}
    contextual: List[str] = []
    allowed = _connectable_tags(audit, options)

    for tag, status in audit.features.items():
        if not status.has_gaps:
            continue
        if status.state == FeatureState.ABSENT:
            continue
        if tag not in allowed:
            continue
        if not status.missing_pairs and not status.missing_ligatures:
            continue
        features[tag] = status
        if status.connect_tier == ConnectTier.CONTEXTUAL:
            contextual.append(tag)

    for tag, status in audit.stylistic_sets.items():
        if tag not in allowed:
            continue
        if status.has_gaps and status.missing_pairs:
            stylistic_sets[tag] = status

    return ConnectPlan(
        path=audit.path,
        features=features,
        stylistic_sets=stylistic_sets,
        contextual_tags=contextual,
        skipped=_skipped_from_recommendations(audit, options),
    )


def render_connect_fea(audit: FontFeatureAudit, plan: ConnectPlan, font: TTFont) -> str:
    blocks: List[str] = []
    blocks.append(f"# Connect plan for {audit.path.name}")
    blocks.append("# Generated reconnections only — review before applying")
    if plan.contextual_tags:
        blocks.append(
            "# Contextual features: merge apply will skip these — wire manually if needed"
        )
    blocks.append("")

    for entry in LIGATURE_FEATURES:
        status = plan.features.get(entry.tag)
        if not status or not status.missing_ligatures:
            continue
        ligs = [(list(c), g) for c, g in status.missing_ligatures]
        fea = generate_feature_fea(entry, ligatures=ligs)
        if fea:
            blocks.append(fea)
            blocks.append("")

    for entry in SINGLE_FEATURES:
        status = plan.features.get(entry.tag)
        if not status or not status.missing_pairs:
            continue
        fea = generate_feature_fea(entry, pairs=status.missing_pairs, font=font)
        if fea:
            blocks.append(fea)
            blocks.append("")

    frac_status = plan.features.get(FRAC_FEATURE.tag)
    if frac_status and frac_status.missing_pairs:
        fea = generate_feature_fea(
            FRAC_FEATURE,
            numerators=frac_status.frac_numerators,
            denominators=frac_status.frac_denominators,
            font=font,
        )
        if fea:
            blocks.append(fea)
            blocks.append("")

    for tag, status in sorted(plan.stylistic_sets.items()):
        if not status.missing_pairs:
            continue
        ss_num = int(tag[2:])
        fea = FeatureCodeGenerator.generate_stylistic_set_feature(
            ss_num, status.missing_pairs
        )
        if fea:
            blocks.append(fea)
            blocks.append("")

    return "\n".join(blocks).strip() + "\n"


_TIER_LABEL = {
    RecommendTier.HIGH: "HIGH",
    RecommendTier.MEDIUM: "MED",
    RecommendTier.LOW: "LOW",
    RecommendTier.MANUAL: "MANUAL",
}


def _rec_tier_for_tag(audit: FontFeatureAudit, tag: str) -> str:
    for rec in audit.recommendations:
        if rec.tag == tag:
            return _TIER_LABEL.get(rec.tier, rec.tier.value.upper())
    return ""


def emit_connect_preview(
    audit: FontFeatureAudit,
    plan: ConnectPlan,
    *,
    options: ConnectOptions | None = None,
) -> None:
    options = options or ConnectOptions()

    if plan.blocked:
        cs.StatusIndicator("warning").add_message(
            f"Connect blocked: {plan.path.name}"
        ).with_explanation(plan.block_reason).emit()
        if plan.skipped:
            cs.StatusIndicator("info").add_message(
                f"  {len(plan.skipped)} feature gap(s) noted by scan (not in plan)"
            ).emit()
        return

    if not plan.has_work:
        cs.StatusIndicator("unchanged").add_message(
            "No reconnections needed"
        ).emit()
        if plan.skipped:
            for item in plan.skipped[:5]:
                cs.StatusIndicator("info").add_message(
                    f"  skipped {item.tag}: {item.reason}"
                ).emit()
            if len(plan.skipped) > 5:
                cs.StatusIndicator("info").add_message(
                    f"  … and {len(plan.skipped) - 5} more skipped"
                ).emit()
        return

    tier_note = "HIGH+MED"
    if options.include_low:
        tier_note += "+LOW"
    if options.include_manual:
        tier_note += "+MANUAL"

    cs.StatusIndicator("info").add_message(
        f"Connect plan: {plan.path.name} ({plan.rule_count()} rule(s), {tier_note})"
    ).emit()

    for tag, status in sorted(plan.features.items()):
        missing = len(status.missing_pairs) + len(status.missing_ligatures)
        tier = _rec_tier_for_tag(audit, tag)
        tier_prefix = f"[{tier}] " if tier else ""
        note = ""
        if tag in plan.contextual_tags:
            note = " — contextual; auto-apply will skip"
        cs.StatusIndicator("info").add_message(
            f"  {tier_prefix}{tag}: {missing} rule(s){note}"
        ).emit()

    for tag, status in sorted(plan.stylistic_sets.items()):
        tier = _rec_tier_for_tag(audit, tag)
        tier_prefix = f"[{tier}] " if tier else ""
        cs.StatusIndicator("info").add_message(
            f"  {tier_prefix}{tag}: {len(status.missing_pairs)} rule(s)"
        ).emit()

    if plan.skipped:
        cs.StatusIndicator("info").add_message("  Skipped by policy:").emit()
        for item in plan.skipped[:8]:
            tier = f"[{item.tier}] " if item.tier else ""
            cs.StatusIndicator("info").add_message(
                f"    {tier}{item.tag}: {item.reason}"
            ).emit()
        if len(plan.skipped) > 8:
            cs.StatusIndicator("info").add_message(
                f"    … and {len(plan.skipped) - 8} more"
            ).emit()

    if plan.contextual_tags:
        cs.StatusIndicator("warning").add_message(
            "Contextual features in FEA — review before apply; merge skips them"
        ).with_explanation(", ".join(plan.contextual_tags)).emit()


def confirm_connect_apply(plan_count: int, *, auto_yes: bool) -> bool:
    if plan_count == 0:
        return False
    if auto_yes:
        return True
    try:
        answer = input(
            f"Apply reconnections to {plan_count} font(s)? [y/N]: "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("y", "yes")
