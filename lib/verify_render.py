"""Terminal rendering for OpentypeFlow verify results."""

from __future__ import annotations

from pathlib import Path
from typing import List

from .verify import VerifyFinding, VerifyReport, VerifySeverity


def _severity_label(finding: VerifyFinding) -> str:
    return {
        VerifySeverity.ERROR: "ERROR",
        VerifySeverity.WARNING: "WARN",
        VerifySeverity.INFO: "INFO",
    }[finding.severity]


def render_verify_report(report: VerifyReport) -> str:
    lines: List[str] = []
    lines.append(f"  {report.path.name}")

    if not report.findings:
        lines.append("    OK — no issues")
        return "\n".join(lines)

    for finding in report.findings:
        lines.append(f"    [{_severity_label(finding)}] {finding.message}")

    return "\n".join(lines)


def render_family_verify(reports: List[VerifyReport], *, parent: Path) -> str:
    lines: List[str] = []
    lines.append(f"Verify: {parent.name} ({len(reports)} font(s))")
    lines.append("-" * 56)

    error_count = sum(len(r.errors) for r in reports)
    warn_count = sum(len(r.warnings) for r in reports)

    for report in reports:
        lines.append(render_verify_report(report))

    lines.append("")
    if error_count == 0 and warn_count == 0:
        lines.append("  All fonts passed verification")
    else:
        lines.append(
            f"  Summary: {error_count} error(s), {warn_count} warning(s) across {len(reports)} font(s)"
        )

    return "\n".join(lines)
