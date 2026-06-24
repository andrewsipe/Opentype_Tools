"""Render FontFeatureAudit to FEA and JSON."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Tuple

from fontTools.ttLib import TTFont

from .feature_generation import FeatureCodeGenerator
from .feature_policy import (
    FRAC_FEATURE,
    LIGATURE_FEATURES,
    SINGLE_FEATURES,
    generate_feature_fea,
)
from .models import FeatureState, FontFeatureAudit


def _sample_pairs(pairs: List[Tuple[str, str]], limit: int = 3) -> str:
    samples = [f"{a}→{b}" for a, b in pairs[:limit]]
    if len(pairs) > limit:
        samples.append(f"({len(pairs) - limit} more)")
    return ", ".join(samples)


def _comment_fea_block(fea_code: str, header_lines: List[str]) -> List[str]:
    lines: List[str] = []
    for h in header_lines:
        lines.append(f"# {h}")
    lines.append("")
    for line in fea_code.split("\n"):
        lines.append(f"# {line}")
    lines.append("")
    return lines


def render_audit_fea(audit: FontFeatureAudit, font: TTFont, *, suggest: bool = True) -> str:
    sections: List[str] = []

    if audit.active_fea:
        sections.append("# " + "=" * 50)
        sections.append("# EXISTING ACTIVE FEATURES")
        sections.append(f"# Extracted from font on {datetime.now().strftime('%Y-%m-%d')}")
        sections.append("# " + "=" * 50)
        sections.append("")
        sections.append(audit.active_fea)
        sections.append("")

    inactive_blocks: List[Tuple[str, str, int, str]] = []
    suggested_blocks: List[Tuple[str, str, int, str]] = []

    for tag, status in sorted(audit.stylistic_sets.items()):
        if status.state not in (FeatureState.INACTIVE, FeatureState.PARTIAL):
            continue
        if not status.missing_pairs:
            continue
        ss_num = int(tag[2:])
        fea = FeatureCodeGenerator.generate_stylistic_set_feature(
            ss_num, status.missing_pairs
        )
        inactive_blocks.append((tag, status.label, status.missing_pairs, fea))

    if inactive_blocks:
        sections.append("# " + "=" * 50)
        sections.append("# INACTIVE / PARTIAL FEATURES")
        sections.append("# Glyphs exist but substitutions are missing")
        sections.append("# Uncomment blocks below to enable")
        sections.append("# " + "=" * 50)
        sections.append("")
        for tag, label, missing, fea_code in inactive_blocks:
            sections.extend(
                _comment_fea_block(
                    fea_code,
                    [
                        f"{tag.upper()}: {label} ({len(missing)} missing)",
                        f"Detected: {_sample_pairs(missing)}",
                    ],
                )
            )

    if suggest:
        for entry in list(SINGLE_FEATURES) + list(LIGATURE_FEATURES) + [FRAC_FEATURE]:
            status = audit.features.get(entry.tag)
            if not status or status.state == FeatureState.ABSENT:
                continue
            if status.state == FeatureState.ACTIVE:
                continue

            if entry.kind == "ligature":
                ligs = [(list(c), g) for c, g in status.missing_ligatures]
                if not ligs:
                    continue
                fea = generate_feature_fea(entry, ligatures=ligs)
                count = len(ligs)
            elif entry.kind == "frac":
                if not status.missing_pairs:
                    continue
                fea = generate_feature_fea(
                    entry,
                    numerators=status.frac_numerators,
                    denominators=status.frac_denominators,
                    font=font,
                )
                count = len(status.missing_pairs)
            else:
                if not status.missing_pairs:
                    continue
                fea = generate_feature_fea(entry, pairs=status.missing_pairs, font=font)
                count = len(status.missing_pairs)

            if fea:
                suggested_blocks.append((entry.tag, entry.label, count, fea))

        if suggested_blocks:
            sections.append("# " + "=" * 50)
            sections.append("# SUGGESTED RECONNECTIONS")
            sections.append("# Based on glyph naming patterns")
            sections.append("# Review carefully before uncommenting")
            sections.append("# " + "=" * 50)
            sections.append("")
            for tag, label, count, fea_code in suggested_blocks:
                status = audit.features.get(tag)
                sample = _sample_pairs(status.missing_pairs if status else [])
                sections.extend(
                    _comment_fea_block(
                        fea_code,
                        [f"{label} ({count} glyphs)", f"Detected: {sample}"],
                    )
                )

    return "\n".join(sections)


def render_audit_json(audit: FontFeatureAudit) -> Dict[str, object]:
    def _status_dict(status) -> Dict[str, object]:
        return {
            "tag": status.tag,
            "label": status.label,
            "state": status.state.value,
            "connect_tier": status.connect_tier.value,
            "detected_count": len(status.detected_pairs)
            + len(status.ligatures),
            "wired_count": len(status.wired_pairs)
            + len([1 for c, _ in status.ligatures if c not in dict(status.missing_ligatures)]),
            "missing_count": len(status.missing_pairs) + len(status.missing_ligatures),
            "missing_pairs": status.missing_pairs[:20],
            "missing_ligatures": [
                {"components": list(c), "glyph": g}
                for c, g in status.missing_ligatures[:20]
            ],
        }

    return {
        "font": str(audit.path),
        "timestamp": datetime.now().isoformat(),
        "existing_features": sorted(audit.existing_tags),
        "gsub_features": sorted(audit.gsub_tags),
        "gpos_features": sorted(audit.gpos_tags),
        "installed_feature_details": {
            tag: {
                "table": d.table,
                "lookup_count": d.lookup_count,
                "populated": d.populated,
                "status": d.status_label,
                "in_naming_policy": d.in_naming_policy,
            }
            for tag, d in sorted(audit.installed_features.items())
        },
        "otl_stripped_suspected": audit.otl_stripped_suspected,
        "glyph_inventory": {
            "glyph_count": audit.glyph_inventory.glyph_count,
            "variant_glyph_count": audit.glyph_inventory.variant_glyph_count,
            "unicode_mapped_count": audit.glyph_inventory.unicode_mapped_count,
            "limited_glyph_set": audit.glyph_inventory.limited_glyph_set,
        },
        "recommendations": [
            {
                "tag": r.tag,
                "tier": r.tier.value,
                "reason": r.reason,
                "state": r.state.value,
                "missing_count": r.missing_count,
            }
            for r in audit.recommendations
        ],
        "wrap_status": {
            "needs_scaffolding": audit.wrap_status.needs_scaffolding,
            "can_wrap": audit.wrap_status.can_wrap,
            "reason": audit.wrap_status.reason,
            "outline_kind": audit.wrap_status.outline_kind,
            "wrap_plan_summary": audit.wrap_status.wrap_plan_summary,
            "flagged_unsupported": audit.wrap_status.flagged_unsupported,
        },
        "features": {
            tag: _status_dict(s)
            for tag, s in audit.features.items()
            if s.state != FeatureState.ABSENT
        },
        "stylistic_sets": {
            tag: _status_dict(s)
            for tag, s in audit.stylistic_sets.items()
            if s.state != FeatureState.ABSENT
        },
        "warnings": audit.warnings,
    }
