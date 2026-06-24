"""Terminal rendering for OpentypeFlow scan results."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set

from .models import FontFeatureAudit, LIMITED_GLYPH_SET_THRESHOLD, RecommendTier
from .otl_inventory import empty_installed_tags, tags_beyond_naming_policy


def _format_tag_list(tags: Set[str], *, limit: int = 24) -> str:
    if not tags:
        return "(none)"
    ordered = sorted(tags)
    if len(ordered) <= limit:
        return ", ".join(ordered)
    shown = ", ".join(ordered[:limit])
    return f"{shown} (+{len(ordered) - limit} more)"


def _inventory_note(audit: FontFeatureAudit) -> str | None:
    inv = audit.glyph_inventory
    if inv.limited_glyph_set and not inv.has_variant_glyphs:
        return (
            f"trial/subset candidate — only {inv.glyph_count} glyphs, "
            "no alternates detected"
        )
    if not inv.has_variant_glyphs:
        return "no variant glyphs detected by naming patterns"
    if inv.limited_glyph_set:
        return (
            f"small glyph set ({inv.glyph_count} glyphs) — "
            f"{inv.variant_glyph_count} variant(s) detected"
        )
    return None


def render_glyph_inventory(audits: List[FontFeatureAudit]) -> str:
    lines: List[str] = []
    lines.append("Glyph inventory")
    lines.append("-" * 56)
    lines.append(
        f"  Variant detection uses naming suffixes (e.g. .ss01, .sc, f_f); "
        f"sets under ~{LIMITED_GLYPH_SET_THRESHOLD} glyphs with no variants "
        "are often trials."
    )

    for audit in audits:
        inv = audit.glyph_inventory
        lines.append(
            f"  {audit.path.name}: {inv.glyph_count} glyphs, "
            f"{inv.unicode_mapped_count} Unicode-mapped, "
            f"{inv.variant_glyph_count} variant(s) detected"
        )
        note = _inventory_note(audit)
        if note:
            lines.append(f"    → {note}")

    if len(audits) > 1:
        counts = [a.glyph_inventory.glyph_count for a in audits]
        variants = [a.glyph_inventory.variant_glyph_count for a in audits]
        lines.append("")
        lines.append(
            f"  Family range: {min(counts)}–{max(counts)} glyphs, "
            f"{min(variants)}–{max(variants)} variant(s) per font"
        )

    limited = [a for a in audits if a.glyph_inventory.limited_glyph_set and not a.glyph_inventory.has_variant_glyphs]
    if limited:
        lines.append("")
        lines.append(
            f"  {len(limited)} font(s) look like trial/subset cuts — "
            "feature recovery needs the full glyph set in the export"
        )

    return "\n".join(lines)


def _format_installed_table(audit: FontFeatureAudit, table: str) -> str:
    tags = sorted(audit.gsub_tags if table == "GSUB" else audit.gpos_tags)
    if not tags:
        return "(none)"
    parts: List[str] = []
    for tag in tags:
        detail = audit.installed_features.get(tag)
        if detail and detail.table == table:
            parts.append(f"{tag} ({detail.status_label})")
        else:
            parts.append(tag)
    return ", ".join(parts)


def render_installed_features(audits: List[FontFeatureAudit]) -> str:
    lines: List[str] = []
    lines.append("Installed OpenType features (from font tables)")
    lines.append("-" * 56)
    lines.append("  Tags show populated / empty / lookups-only from OTL lookup depth.")

    for audit in audits:
        lines.append(f"  {audit.path.name}")
        lines.append(f"    GSUB: {_format_installed_table(audit, 'GSUB')}")
        lines.append(f"    GPOS: {_format_installed_table(audit, 'GPOS')}")
        empty = empty_installed_tags(audit.installed_features)
        if empty:
            lines.append(f"    empty or unpopulated: {', '.join(empty)}")
        only_in_font = audit.existing_tags - {
            t
            for other in audits
            if other.path != audit.path
            for t in other.existing_tags
        }
        if len(audits) > 1 and only_in_font:
            lines.append(f"    unique: {_format_tag_list(only_in_font, limit=12)}")

    union_gsub: Set[str] = set()
    union_gpos: Set[str] = set()
    for audit in audits:
        union_gsub |= audit.gsub_tags
        union_gpos |= audit.gpos_tags
    if len(audits) > 1:
        lines.append("")
        lines.append("  Family union")
        lines.append(f"    GSUB: {_format_tag_list(union_gsub)}")
        lines.append(f"    GPOS: {_format_tag_list(union_gpos)}")

    return "\n".join(lines)


def render_installed_beyond_policy(audits: List[FontFeatureAudit]) -> str:
    lines: List[str] = []
    lines.append("Installed beyond naming-policy scan")
    lines.append("-" * 56)
    lines.append(
        "  Present in the font but not evaluated in the glyph-detected matrix below."
    )

    any_extra = False
    for audit in audits:
        beyond = tags_beyond_naming_policy(audit.installed_features)
        if not beyond:
            continue
        any_extra = True
        lines.append(f"  {audit.path.name}")
        gsub = [d for d in beyond if d.table == "GSUB"]
        gpos = [d for d in beyond if d.table == "GPOS"]
        if gsub:
            lines.append(
                "    GSUB: "
                + ", ".join(f"{d.tag} ({d.status_label})" for d in gsub)
            )
        if gpos:
            lines.append(
                "    GPOS: "
                + ", ".join(f"{d.tag} ({d.status_label})" for d in gpos)
            )

    if not any_extra:
        lines.append("  (none beyond policy scope)")

    return "\n".join(lines)


def render_wrap_assessment(audits: List[FontFeatureAudit]) -> str:
    lines: List[str] = []
    lines.append("Wrap assessment (scaffolding + enrichment preview)")
    lines.append("-" * 56)

    any_wrap = False
    for audit in audits:
        ws = audit.wrap_status
        if not ws.needs_scaffolding and not audit.otl_stripped_suspected:
            continue
        any_wrap = True
        kind = ws.outline_kind or "unknown"
        status = "ready" if ws.can_wrap else "unsupported"
        lines.append(f"  {audit.path.name} [{kind}, {status}]")
        if ws.reason:
            lines.append(f"    {ws.reason}")
        if audit.otl_stripped_suspected:
            lines.append(
                "    Suspected stripped/omitted OTL — wrap recommended before connect"
            )
        if ws.wrap_plan_summary:
            for plan_line in ws.wrap_plan_summary.split("\n"):
                lines.append(f"    {plan_line}")

    if not any_wrap:
        lines.append("  All fonts have basic OTL scaffolding")

    return "\n".join(lines)


def render_glyph_detection_matrix(audits: List[FontFeatureAudit]) -> str:
    """Feature state counts from glyph naming (policy scope only)."""
    from .family_rollup import build_family_summary, render_family_matrix

    if not audits:
        return ""
    parent = audits[0].path.parent
    summary = build_family_summary(parent, audits)
    body = render_family_matrix(summary)
    # Drop duplicate header lines from legacy renderer; keep matrix table + attention.
    parts = body.split("\n")
    start = 0
    for i, line in enumerate(parts):
        if line.startswith("Feature"):
            start = i
            break
    trimmed = "\n".join(parts[start:])
    return "Glyph-detected features (naming patterns in policy scope)\n" + trimmed


def render_recommendations(audits: List[FontFeatureAudit]) -> str:
    lines: List[str] = []
    lines.append("Recommendations (graded — connect uses high/medium only)")
    lines.append("-" * 56)

    tier_labels = {
        RecommendTier.HIGH: "HIGH",
        RecommendTier.MEDIUM: "MED",
        RecommendTier.LOW: "LOW",
        RecommendTier.MANUAL: "MANUAL",
    }

    any_recs = False
    for audit in audits:
        if not audit.recommendations:
            continue
        any_recs = True
        lines.append(f"  {audit.path.name}")
        by_tier: Dict[RecommendTier, List[str]] = defaultdict(list)
        for rec in audit.recommendations:
            label = tier_labels.get(rec.tier, rec.tier.value.upper())
            detail = f"{rec.tag} ({rec.missing_count} unwired) — {rec.reason}"
            by_tier[rec.tier].append(detail)

        for tier in (
            RecommendTier.HIGH,
            RecommendTier.MEDIUM,
            RecommendTier.LOW,
            RecommendTier.MANUAL,
        ):
            items = by_tier.get(tier)
            if not items:
                continue
            lines.append(f"    [{tier_labels[tier]}]")
            for item in items:
                lines.append(f"      • {item}")

    if not any_recs:
        no_variants = all(not a.glyph_inventory.has_variant_glyphs for a in audits)
        limited = all(a.glyph_inventory.limited_glyph_set for a in audits)
        if no_variants and limited:
            lines.append(
                "  No connect recommendations — small glyph set with no variant suffixes"
            )
        elif no_variants:
            lines.append(
                "  No connect recommendations — no variant glyphs detected by naming"
            )
        else:
            lines.append(
                "  No connect recommendations — installed features match detected glyphs"
            )

    skipped_salt = 0
    for audit in audits:
        salt = audit.features.get("salt")
        if salt and salt.has_gaps and not any(r.tag == "salt" for r in audit.recommendations):
            skipped_salt += 1
    if skipped_salt:
        lines.append("")
        lines.append(
            f"  Note: salt skipped for {skipped_salt} font(s) where ss/swsh/calt already cover alternates"
        )

    return "\n".join(lines)


def render_family_scan(audits: List[FontFeatureAudit], *, parent: Path) -> str:
    sections = [
        f"Scan: {parent.name} ({len(audits)} font(s))",
        "",
        render_glyph_inventory(audits),
        "",
        render_installed_features(audits),
        "",
        render_installed_beyond_policy(audits),
        "",
        render_wrap_assessment(audits),
        "",
        render_glyph_detection_matrix(audits),
        "",
        render_recommendations(audits),
    ]
    return "\n".join(sections)
