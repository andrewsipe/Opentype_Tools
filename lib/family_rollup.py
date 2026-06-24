"""Family-level rollups from per-font audits."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from .io_paths import family_matrix_path, family_summary_path
from .models import FeatureState, FontFeatureAudit


def _tag_counts(audits: List[FontFeatureAudit]) -> Dict[str, Dict[str, int]]:
    counts: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {
            FeatureState.ACTIVE.value: 0,
            FeatureState.PARTIAL.value: 0,
            FeatureState.INACTIVE.value: 0,
            FeatureState.ABSENT.value: 0,
        }
    )

    for audit in audits:
        all_statuses = list(audit.features.values()) + list(audit.stylistic_sets.values())
        for status in all_statuses:
            if status.state == FeatureState.ABSENT:
                continue
            counts[status.tag][status.state.value] += 1

    return dict(counts)


def fonts_needing_attention(audits: List[FontFeatureAudit]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for audit in audits:
        gaps = audit.gaps()
        wrap_needed = audit.wrap_status.needs_scaffolding and audit.wrap_status.can_wrap
        if not gaps and not wrap_needed and not audit.wrap_status.flagged_unsupported:
            continue
        row: Dict[str, object] = {
            "font": audit.path.name,
            "path": str(audit.path),
            "glyph_count": audit.glyph_inventory.glyph_count,
            "variant_glyph_count": audit.glyph_inventory.variant_glyph_count,
            "gaps": [
                {
                    "tag": g.tag,
                    "label": g.label,
                    "state": g.state.value,
                    "missing": len(g.missing_pairs) + len(g.missing_ligatures),
                }
                for g in gaps
            ],
            "recommendations": [
                {
                    "tag": r.tag,
                    "tier": r.tier.value,
                    "reason": r.reason,
                    "missing": r.missing_count,
                }
                for r in audit.recommendations
            ],
        }
        if wrap_needed:
            row["wrap_needed"] = audit.wrap_status.reason
        if audit.otl_stripped_suspected:
            row["otl_stripped_suspected"] = True
        if audit.wrap_status.flagged_unsupported:
            row["wrap_flag"] = audit.wrap_status.reason
        rows.append(row)
    return rows


def build_family_summary(
    parent_dir: Path,
    audits: List[FontFeatureAudit],
) -> Dict[str, object]:
    wrap_flagged = [
        str(a.path)
        for a in audits
        if a.wrap_status.flagged_unsupported
    ]
    wrap_needed = [
        str(a.path)
        for a in audits
        if a.wrap_status.needs_scaffolding and a.wrap_status.can_wrap
    ]
    installed_gsub = sorted({t for a in audits for t in a.gsub_tags})
    installed_gpos = sorted({t for a in audits for t in a.gpos_tags})
    glyph_counts = [a.glyph_inventory.glyph_count for a in audits]
    variant_counts = [a.glyph_inventory.variant_glyph_count for a in audits]
    return {
        "directory": str(parent_dir),
        "timestamp": datetime.now().isoformat(),
        "font_count": len(audits),
        "fonts": [str(a.path) for a in audits],
        "installed_gsub": installed_gsub,
        "installed_gpos": installed_gpos,
        "glyph_inventory": {
            "min_glyph_count": min(glyph_counts) if glyph_counts else 0,
            "max_glyph_count": max(glyph_counts) if glyph_counts else 0,
            "max_variant_glyph_count": max(variant_counts) if variant_counts else 0,
        },
        "feature_counts": _tag_counts(audits),
        "fonts_needing_attention": fonts_needing_attention(audits),
        "wrap_needed": wrap_needed,
        "wrap_flagged": wrap_flagged,
    }


def render_family_matrix(summary: Dict[str, object]) -> str:
    lines: List[str] = []
    lines.append(f"Family summary: {summary.get('directory', '')}")
    lines.append(f"Fonts: {summary.get('font_count', 0)}")
    lines.append("")
    lines.append(f"{'Feature':<12} {'Active':>8} {'Partial':>8} {'Inactive':>8}")
    lines.append("-" * 40)

    feature_counts = summary.get("feature_counts", {})
    for tag in sorted(feature_counts.keys()):
        c = feature_counts[tag]
        lines.append(
            f"{tag:<12} {c.get('active', 0):>8} {c.get('partial', 0):>8} {c.get('inactive', 0):>8}"
        )

    installed_gsub = summary.get("installed_gsub", [])
    installed_gpos = summary.get("installed_gpos", [])
    if installed_gsub or installed_gpos:
        lines.append("")
        lines.append("Installed (family union)")
        if installed_gsub:
            lines.append(f"  GSUB: {', '.join(installed_gsub)}")
        if installed_gpos:
            lines.append(f"  GPOS: {', '.join(installed_gpos)}")

    attention = summary.get("fonts_needing_attention", [])
    if attention:
        lines.append("")
        lines.append("Fonts needing attention:")
        for item in attention:
            font = item.get("font", "")
            gaps = item.get("gaps", [])
            gap_str = ", ".join(
                f"{g['tag']} ({g['state']})" for g in gaps if isinstance(g, dict)
            )
            recs = item.get("recommendations", [])
            rec_str = ", ".join(
                f"{r['tag']} [{r['tier']}]" for r in recs if isinstance(r, dict)
            )
            wrap = item.get("wrap_needed") or item.get("wrap_flag")
            parts = [
                p
                for p in [
                    gap_str,
                    f"recommend: {rec_str}" if rec_str else "",
                    f"wrap: {wrap}" if wrap else "",
                ]
                if p
            ]
            lines.append(f"  {font}: {'; '.join(parts)}")

    wrap_needed = summary.get("wrap_needed", [])
    if wrap_needed:
        lines.append("")
        lines.append("Fonts needing wrap:")
        for p in wrap_needed:
            lines.append(f"  {Path(p).name}")

    wrap_flagged = summary.get("wrap_flagged", [])
    if wrap_flagged:
        lines.append("")
        lines.append("Fonts where wrap is unsupported:")
        for p in wrap_flagged:
            lines.append(f"  {Path(p).name}")

    return "\n".join(lines)


def write_family_artifacts(
    parent_dir: Path,
    audits: List[FontFeatureAudit],
    *,
    scan_root: Path | None = None,
    output_dir: Path | None = None,
) -> None:
    summary = build_family_summary(parent_dir, audits)
    summary_path = family_summary_path(
        parent_dir, scan_root=scan_root, output_dir=output_dir
    )
    matrix_path = family_matrix_path(
        parent_dir, scan_root=scan_root, output_dir=output_dir
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    matrix_path.write_text(render_family_matrix(summary), encoding="utf-8")
