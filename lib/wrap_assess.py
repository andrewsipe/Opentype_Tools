"""Assess whether a font needs OpenType scaffolding and can be wrapped."""

from __future__ import annotations

from fontTools.ttLib import TTFont

from .models import WrapStatus
from .validation import FontValidator
from .wrapper import WrapperStrategyEngine


def sfnt_version(font: TTFont) -> bytes | None:
    reader = getattr(font, "reader", None)
    if reader is None:
        return None
    return getattr(reader, "sfntVersion", None)


def outline_kind(font: TTFont) -> str:
    ver = sfnt_version(font)
    if ver in (b"\x00\x01\x00\x00", b"true"):
        return "truetype"
    if ver == b"OTTO":
        return "cff"
    # In-memory fonts (e.g. FontBuilder) may not expose sfntVersion on reader.
    if "CFF " in font or "CFF2" in font:
        return "cff"
    if "glyf" in font:
        return "truetype"
    return "unknown"


def is_wrappable_sfnt(font: TTFont) -> bool:
    """True for TrueType-outline and CFF OpenType sfnt fonts."""
    return outline_kind(font) in ("truetype", "cff")


def is_truetype_outline_sfnt(font: TTFont) -> bool:
    """True if font uses sfnt glyf/TrueType outline (legacy helper)."""
    return outline_kind(font) == "truetype"


def _scaffolding_parts(state) -> list[str]:
    parts: list[str] = []
    if not state.has_gsub:
        parts.append("missing GSUB")
    if not state.has_gpos:
        parts.append("missing GPOS")
    if not state.has_gdef:
        parts.append("missing GDEF")
    if state.is_empty_otl():
        parts.append("empty OTL")
    return parts


def assess_wrap_status(font: TTFont, *, preview_plan: bool = True) -> WrapStatus:
    """Determine wrap eligibility, scaffolding needs, and optional dry-run plan."""
    validator = FontValidator(font)
    state = validator.state
    kind = outline_kind(font)
    needs = state.needs_basic_scaffolding() or state.is_empty_otl()
    can_wrap = is_wrappable_sfnt(font)

    if not needs:
        return WrapStatus(
            needs_scaffolding=False,
            can_wrap=can_wrap,
            outline_kind=kind,
        )

    if not can_wrap:
        return WrapStatus(
            needs_scaffolding=True,
            can_wrap=False,
            reason="Unsupported font container — wrap not available",
            outline_kind=kind,
        )

    parts = _scaffolding_parts(state)
    label = "TrueType" if kind == "truetype" else "OpenType/CFF"
    reason = f"{label} font needs scaffolding: " + ", ".join(parts)

    wrap_plan_summary = ""
    if preview_plan:
        engine = WrapperStrategyEngine(font, validator)
        plan, _ = engine.create_plan(
            {"enrich": True, "skip_validation": False, "overwrite_cmap": False}
        )
        if plan.has_work():
            wrap_plan_summary = plan.summarize()

    return WrapStatus(
        needs_scaffolding=True,
        can_wrap=True,
        reason=reason,
        outline_kind=kind,
        wrap_plan_summary=wrap_plan_summary,
    )
