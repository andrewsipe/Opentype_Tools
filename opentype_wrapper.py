#!/usr/bin/env python3
"""
Convert TrueType fonts to OpenType with intelligent enrichment.

Adds OpenType table scaffolding and intelligently migrates legacy data
without requiring explicit flags. Validates before every operation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from lib.fontcore_path import ensure_fontcore_on_path  # noqa: E402

ensure_fontcore_on_path(_TOOLS_DIR)

import FontCore.core_console_styles as cs  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

from lib.coverage import sort_coverage_tables_in_font  # noqa: E402
from lib.utils import atomic_ttfont_save, backup_font, collect_font_files  # noqa: E402
from lib.validation import FontValidator  # noqa: E402
from lib.wrapper import WrapperExecutor, WrapperStrategyEngine  # noqa: E402


def _is_truetype_outline_sfnt(font: TTFont) -> bool:
    """True if font uses sfnt glyf/TrueType outline (wrapper target); False for ``OTTO``/CFF-only."""
    reader = getattr(font, "reader", None)
    if reader is None:
        return False
    ver = getattr(reader, "sfntVersion", None)
    return ver in (b"\x00\x01\x00\x00", b"true")


def main() -> int:
    """Main entry point for wrapper CLI."""
    parser = argparse.ArgumentParser(
        description="Convert TrueType fonts to OpenType with intelligent enrichment"
    )
    parser.add_argument(
        "fonts",
        nargs="+",
        help="Font files or directories to process",
    )
    parser.add_argument(
        "--recursive",
        "-r",
        action="store_true",
        help="Search directories recursively",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--overwrite-cmap",
        action="store_true",
        help="Force cmap rebuild (may lose entries)",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip destructive validations; disables enrichment (scaffolding only)",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Only add table scaffolding, no enrichment",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not save a numbered copy under backups/ before overwriting the original",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )

    args = parser.parse_args()

    enrich = not args.no_enrich and not args.skip_validation
    backup_before_save = not args.no_backup

    font_files = collect_font_files(args.fonts, recursive=args.recursive)

    if not font_files:
        cs.StatusIndicator("error").add_message("No font files found").emit()
        return 1

    cs.StatusIndicator("info").add_message(
        f"Found {len(font_files)} font file(s)"
    ).emit()
    cs.emit("")
    if args.skip_validation:
        cs.StatusIndicator("warning").add_message(
            "Scaffold-only pipeline: destructive overwrite validations skipped; enrichment disabled"
        ).emit()
        cs.emit("")

    success_count = 0
    error_count = 0

    for font_path in font_files:
        cs.StatusIndicator("parsing").add_message(
            f"Processing: {font_path.name}"
        ).emit()

        try:
            with TTFont(font_path, lazy=False) as font:
                if not _is_truetype_outline_sfnt(font):
                    cs.StatusIndicator("warning").add_message(
                        "Skipping font (not TrueType-outline sfnt)"
                    ).with_explanation(
                        "This wrapper targets fonts with glyf outlines "
                        "(sfnt \\x00\\x01\\x00\\x00 or ``true``), not OTTO/CFF‑only shells."
                    ).emit()
                    success_count += 1
                    cs.emit("")
                    continue

                user_prefs = {
                    "overwrite_cmap": args.overwrite_cmap,
                    "enrich": enrich,
                    "skip_validation": args.skip_validation,
                }

                validator = FontValidator(font)
                strategy_engine = WrapperStrategyEngine(font, validator)
                plan, plan_result = strategy_engine.create_plan(user_prefs)

                if args.verbose:
                    plan_result.emit_all()
                else:
                    for msg in plan_result.messages:
                        if msg.level.value in ("error", "warning", "critical"):
                            cs.StatusIndicator(msg.level.value).add_message(
                                msg.message
                            ).with_explanation(msg.details).emit()

                if not plan_result.success:
                    cs.StatusIndicator("error").add_message(
                        "Validation failed",
                        "Cannot proceed. Fix issues or adjust flags.",
                    ).emit()
                    error_count += 1
                    cs.emit("")
                    continue

                if not plan.has_work():
                    cs.StatusIndicator("unchanged").add_message(
                        "No wrapper operations needed"
                    ).with_explanation(
                        "Font already has complete OpenType tables"
                    ).emit()
                    success_count += 1
                    cs.emit("")
                    continue

                enrichment_ops = []
                if plan.can_migrate_kern:
                    enrichment_ops.append(
                        f"Migrate {plan.kern_pair_count} kern pairs to GPOS"
                    )
                if plan.can_infer_liga:
                    enrichment_ops.append(
                        f"Add {len(plan.liga_ligatures)} ligatures to GSUB"
                    )
                if plan.can_enrich_gdef:
                    gdef_details = []
                    if plan.mark_count > 0:
                        gdef_details.append(f"{plan.mark_count} mark classes")
                    if plan.ligature_caret_count > 0:
                        gdef_details.append(
                            f"{plan.ligature_caret_count} ligature carets"
                        )
                    if gdef_details:
                        enrichment_ops.append(
                            f"Enrich GDEF with {', '.join(gdef_details)}"
                        )

                has_existing_features = (
                    validator.state.gsub_lookup_count > 0
                    or validator.state.gpos_lookup_count > 0
                )

                explanation_parts = []
                if has_existing_features:
                    explanation_parts.append(
                        f"Font has {validator.state.gsub_lookup_count} GSUB and "
                        f"{validator.state.gpos_lookup_count} GPOS lookups. "
                        "New features will be merged with existing ones."
                    )

                if enrichment_ops:
                    explanation_parts.append(
                        "\n".join(f"  • {op}" for op in enrichment_ops)
                    )
                else:
                    explanation_parts.append("  • NONE")

                cs.StatusIndicator("info").add_message(
                    "Enrichment opportunities:"
                ).with_explanation("\n".join(explanation_parts)).emit()

                if args.dry_run:
                    cs.StatusIndicator("preview", dry_run=True).add_message(
                        "Would perform:"
                    ).with_explanation(plan.summarize()).emit()
                    success_count += 1
                    cs.emit("")
                    continue

                executor = WrapperExecutor(font, plan)
                exec_result, has_changes = executor.execute()

                if args.verbose:
                    exec_result.emit_all()
                else:
                    for msg in exec_result.messages:
                        if msg.level.value in ("error", "warning", "critical"):
                            cs.StatusIndicator(msg.level.value).add_message(
                                msg.message
                            ).with_explanation(msg.details).emit()

                if exec_result.success:
                    coverage_sorted = 0
                    coverage_total = 0
                    if "GSUB" in font or "GPOS" in font:
                        try:
                            coverage_total, coverage_sorted = (
                                sort_coverage_tables_in_font(font, verbose=args.verbose)
                            )
                        except Exception as e:
                            cs.StatusIndicator("warning").add_message(
                                f"Failed to sort Coverage tables: {e}"
                            ).with_explanation(
                                "Font will be saved but Coverage tables may not be sorted"
                            ).emit()

                    changes_made = list(exec_result.changelog)

                    if coverage_sorted > 0:
                        changes_made.append(
                            f"Sorted {coverage_sorted} of {coverage_total} "
                            "Coverage table(s)"
                        )

                    if coverage_sorted > 0:
                        has_changes = True

                    changes_made = [c for c in changes_made if c and c.strip()]

                    if has_changes and changes_made:
                        cs.StatusIndicator("updated").add_message(
                            "Changes applied:"
                        ).with_explanation(
                            "\n".join(f"  • {change}" for change in changes_made)
                        ).emit()
                    elif not has_changes:
                        cs.StatusIndicator("unchanged").add_message(
                            "No changes made"
                        ).with_explanation(
                            "Font already has all requested features or enrichment failed"
                        ).emit()

                    if has_changes:
                        if backup_before_save:
                            backup_path = backup_font(font_path)
                            rel = backup_path.relative_to(font_path.parent)
                            cs.StatusIndicator("info").add_message(
                                f"Created backup: {rel}"
                            ).emit()
                        atomic_ttfont_save(font, font_path)
                        cs.StatusIndicator("saved").add_message(
                            f"Saved: {font_path.name}"
                        ).emit()

                    success_count += 1
                else:
                    cs.StatusIndicator("error").add_message(
                        "Wrapper execution failed"
                    ).emit()
                    error_count += 1

        except Exception as e:
            cs.StatusIndicator("error").add_message(
                f"Failed to process {font_path.name}: {e}"
            ).emit()
            error_count += 1

        cs.emit("")

    cs.StatusIndicator("success").add_message(
        "Processing Complete"
    ).with_summary_block(updated=success_count, errors=error_count).emit()

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
