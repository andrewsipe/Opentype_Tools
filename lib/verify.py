"""Post-workflow verification for OpentypeFlow fonts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List

from fontTools.ttLib import TTFont

from .analyze import analyze_font
from .models import ConnectOptions, FontFeatureAudit
from .otl_inventory import empty_installed_tags
from .recommendations import RecommendTier, connect_allowed


class VerifySeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class VerifyFinding:
    severity: VerifySeverity
    message: str


@dataclass
class VerifyReport:
    path: Path
    audit: FontFeatureAudit
    findings: List[VerifyFinding] = field(default_factory=list)

    @property
    def errors(self) -> List[VerifyFinding]:
        return [f for f in self.findings if f.severity == VerifySeverity.ERROR]

    @property
    def warnings(self) -> List[VerifyFinding]:
        return [f for f in self.findings if f.severity == VerifySeverity.WARNING]

    @property
    def infos(self) -> List[VerifyFinding]:
        return [f for f in self.findings if f.severity == VerifySeverity.INFO]

    @property
    def passed(self) -> bool:
        return not self.errors


def _gsub_missing_script_list(font: TTFont) -> bool:
    if "GSUB" not in font:
        return False
    gsub = font["GSUB"].table
    if not gsub.FeatureList or not gsub.FeatureList.FeatureRecord:
        return False
    if not gsub.ScriptList or not gsub.ScriptList.ScriptCount:
        return True
    return False


def verify_font(
    font: TTFont,
    path: Path,
    *,
    options: ConnectOptions | None = None,
) -> VerifyReport:
    """Run read-only verification checks on one font."""
    options = options or ConnectOptions()
    audit = analyze_font(font, path)
    report = VerifyReport(path=path.resolve(), audit=audit)

    for rec in audit.recommendations:
        if not connect_allowed(
            rec.tier,
            include_low=options.include_low,
            include_manual=options.include_manual,
        ):
            continue
        if rec.tier in (RecommendTier.HIGH, RecommendTier.MEDIUM):
            report.findings.append(
                VerifyFinding(
                    VerifySeverity.ERROR,
                    f"{rec.tag}: {rec.missing_count} unwired — {rec.reason}",
                )
            )

    if audit.otl_stripped_suspected:
        report.findings.append(
            VerifyFinding(
                VerifySeverity.ERROR,
                "OTL still empty/stripped despite detected variant glyphs",
            )
        )

    empty_tags = empty_installed_tags(audit.installed_features)
    if empty_tags:
        report.findings.append(
            VerifyFinding(
                VerifySeverity.WARNING,
                f"Empty feature shell(s): {', '.join(empty_tags)}",
            )
        )

    if _gsub_missing_script_list(font):
        report.findings.append(
            VerifyFinding(
                VerifySeverity.WARNING,
                "GSUB features present but ScriptList is empty (apps may not list features)",
            )
        )

    inv = audit.glyph_inventory
    if inv.limited_glyph_set and not inv.has_variant_glyphs:
        report.findings.append(
            VerifyFinding(
                VerifySeverity.INFO,
                f"Small glyph set ({inv.glyph_count} glyphs) — limited reconnect scope",
            )
        )

    return report


def verify_passes(report: VerifyReport, *, strict: bool = False) -> bool:
    if report.errors:
        return False
    if strict and report.warnings:
        return False
    return True
