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
        cs.StatusIndicator("info").add_message(f"Processing: {font_path.name}").emit()

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
                    cs.StatusIndicator("info").add_message(
                        "No wrapper operations needed"
                    ).emit()
                    font.close()
                    success_count += 1
                    cs.emit("")
                    continue

                if args.dry_run:
                    cs.StatusIndicator("info").add_message(
                        "DRY RUN - would perform:"
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
                    if "GSUB" in font or "GPOS" in font:
                        try:
                            total, sorted_count = sort_coverage_tables_in_font(
                                font, verbose=args.verbose
                            )
                            if sorted_count > 0:
                                cs.StatusIndicator("info").add_message(
                                    f"Sorted {sorted_count} of {total} Coverage table(s)"
                                ).emit()
                        except Exception as e:
                            cs.StatusIndicator("warning").add_message(
                                f"Failed to sort Coverage tables: {e}"
                            ).with_explanation(
                                "Font will be saved but Coverage tables may not be sorted"
                            ).emit()

                    # Only save if actual changes were made
                    if has_changes:
                        font.save(font_path)
                        cs.StatusIndicator("success").add_message(
                            f"Saved: {font_path.name}"
                        ).emit()
                        success_count += 1
                    else:
                        cs.StatusIndicator("info").add_message(
                            "No changes made"
                        ).emit()
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
        cs.StatusIndicator("info").add_message("Processing complete").with_summary_block(
            updated=success_count, errors=error_count
        ).emit()

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

