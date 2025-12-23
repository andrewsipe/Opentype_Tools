#!/usr/bin/env python3
"""
Convert TrueType fonts to OpenType with intelligent enrichment.

Adds OpenType table scaffolding and intelligently migrates legacy data
without requiring explicit flags. Validates before every operation.
"""

import argparse
import sys
from pathlib import Path

# Add project root to path for FontCore imports
_project_root = Path(__file__).parent
while (
    not (_project_root / "FontCore").exists() and _project_root.parent != _project_root
):
    _project_root = _project_root.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import FontCore.core_console_styles as cs  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

from lib.coverage import sort_coverage_tables_in_font  # noqa: E402
from lib.utils import collect_font_files  # noqa: E402
from lib.validation import FontValidator  # noqa: E402
from lib.wrapper import WrapperExecutor, WrapperStrategyEngine  # noqa: E402


def main():
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
        help="Skip validation checks (danger mode)",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Only add table scaffolding, no enrichment",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )

    args = parser.parse_args()

    # Collect font files
    font_files = collect_font_files(args.fonts, recursive=args.recursive)

    if not font_files:
        cs.StatusIndicator("error").add_message("No font files found").emit()
        return 1

    cs.StatusIndicator("info").add_message(
        f"Found {len(font_files)} font file(s)"
    ).emit()
    cs.emit("")

    success_count = 0
    error_count = 0

    for font_path in font_files:
        cs.StatusIndicator("parsing").add_message(
            f"Processing: {font_path.name}"
        ).emit()

        try:
            font = TTFont(font_path, lazy=False)

            # Build user preferences
            user_prefs = {
                "overwrite_cmap": args.overwrite_cmap,
                "enrich": not args.no_enrich,
            }

            # Validate font (unless skipped)
            if not args.skip_validation:
                validator = FontValidator(font)
                strategy_engine = WrapperStrategyEngine(font, validator)

                # Create plan
                plan, plan_result = strategy_engine.create_plan(user_prefs)

                if args.verbose:
                    plan_result.emit_all()
                else:
                    # Only show errors/warnings in non-verbose mode
                    for msg in plan_result.messages:
                        if msg.level.value in ("error", "warning", "critical"):
                            cs.StatusIndicator(msg.level.value).add_message(
                                msg.message
                            ).with_explanation(msg.details).emit()

                if not plan_result.success:
                    cs.StatusIndicator("error").add_message(
                        "Validation failed",
                        "Cannot proceed. Fix issues or use --skip-validation.",
                    ).emit()
                    font.close()
                    error_count += 1
                    cs.emit("")
                    continue

                if not plan.has_work():
                    cs.StatusIndicator("unchanged").add_message(
                        "No wrapper operations needed"
                    ).with_explanation(
                        "Font already has complete OpenType tables"
                    ).emit()
                    font.close()
                    success_count += 1
                    cs.emit("")
                    continue

                # Show enrichment opportunities before execution
                enrichment_ops = []
                if plan.can_migrate_kern:
                    enrichment_ops.append(
                        f"Migrate {plan.kern_pair_count} kern pairs to GPOS"
                    )
                if plan.can_infer_liga:
                    enrichment_ops.append(f"Add {plan.liga_count} ligatures to GSUB")
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

                # Always show enrichment opportunities, even if none exist
                # Check if font already has substantial OpenType features
                has_existing_features = (
                    validator.state.gsub_lookup_count > 0
                    or validator.state.gpos_lookup_count > 0
                )

                # Build explanation with context about existing features if present
                explanation_parts = []
                if has_existing_features:
                    explanation_parts.append(
                        f"Font has {validator.state.gsub_lookup_count} GSUB and "
                        f"{validator.state.gpos_lookup_count} GPOS lookups. "
                        "New features will be merged with existing ones."
                    )

                # Add enrichment opportunities or "NONE" if none exist
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
                    # Show preview (DRY prefix will be added automatically)
                    cs.StatusIndicator("preview", dry_run=True).add_message(
                        "Would perform:"
                    ).with_explanation(plan.summarize()).emit()
                    font.close()
                    success_count += 1
                    cs.emit("")
                    continue

                # Execute plan
                executor = WrapperExecutor(font, plan)
                exec_result, has_changes = executor.execute()

                if args.verbose:
                    exec_result.emit_all()
                else:
                    # Only show errors/warnings in non-verbose mode
                    for msg in exec_result.messages:
                        if msg.level.value in ("error", "warning", "critical"):
                            cs.StatusIndicator(msg.level.value).add_message(
                                msg.message
                            ).with_explanation(msg.details).emit()

                if exec_result.success:
                    # Sort Coverage tables if GSUB/GPOS tables exist
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

                    # Build unified change summary
                    changes_made = []
                    seen_cmap = False

                    # Extract changes from execution result
                    for msg in exec_result.messages:
                        # Success messages are enrichment operations
                        if msg.level.value == "success":
                            # Skip the "Enrichment completed" summary message
                            if "Enrichment completed" not in msg.message:
                                # Capture enrichment operations
                                if any(
                                    keyword in msg.message
                                    for keyword in ["Migrated", "Added", "Enriched"]
                                ):
                                    changes_made.append(msg.message)
                        # Info messages include scaffolding operations
                        elif msg.level.value == "info":
                            # Check for scaffolding operations - prefer detailed messages
                            if (
                                "Created Unicode cmap" in msg.message
                                or "Added Windows Unicode" in msg.message
                            ):
                                if not seen_cmap:
                                    changes_made.append(msg.message)
                                    seen_cmap = True
                            elif any(
                                keyword in msg.message
                                for keyword in [
                                    "Created empty GDEF",
                                    "Created empty GSUB",
                                    "Created empty GPOS",
                                    "Created DSIG stub",
                                ]
                            ):
                                changes_made.append(msg.message)

                    # Add coverage sorting if it happened
                    if coverage_sorted > 0:
                        changes_made.append(
                            f"Sorted {coverage_sorted} of {coverage_total} Coverage table(s)"
                        )

                    # Update has_changes if coverage was sorted
                    if coverage_sorted > 0:
                        has_changes = True

                    # Filter out any empty strings and show summary only if there are actual changes
                    changes_made = [c for c in changes_made if c and c.strip()]

                    # Show unified change summary only if there are actual changes
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

                    # Only save if actual changes were made
                    if has_changes:
                        font.save(font_path)
                        cs.StatusIndicator("saved").add_message(
                            f"Saved: {font_path.name}"
                        ).emit()
                        success_count += 1
                    else:
                        success_count += 1
                else:
                    cs.StatusIndicator("error").add_message(
                        "Wrapper execution failed"
                    ).emit()
                    error_count += 1

            else:
                # Skip validation mode - just do basic operations
                cs.StatusIndicator("warning").add_message(
                    "Validation skipped - proceeding with basic operations"
                ).emit()
                # This mode would need a simplified execution path
                # For now, we'll just warn and skip
                cs.StatusIndicator("error").add_message(
                    "--skip-validation mode not fully implemented"
                ).emit()
                error_count += 1

            font.close()

        except Exception as e:
            cs.StatusIndicator("error").add_message(
                f"Failed to process {font_path.name}: {e}"
            ).emit()
            error_count += 1

        cs.emit("")

    # Summary
    if len(font_files) > 1:
        cs.StatusIndicator("success").add_message(
            "Processing Complete"
        ).with_summary_block(updated=success_count, errors=error_count).emit()

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
