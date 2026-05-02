#!/usr/bin/env python3
"""
Sort Coverage tables in OpenType fonts by GlyphID.

Ensures Coverage tables are sorted according to GlyphOrder, which is
required by some font processors and prevents validation warnings.
"""

import argparse
import logging
import sys
import warnings
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from lib.fontcore_path import ensure_fontcore_on_path  # noqa: E402

ensure_fontcore_on_path(_TOOLS_DIR)

import FontCore.core_console_styles as cs  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

from lib.coverage import sort_coverage_tables_in_font  # noqa: E402
from lib.utils import atomic_ttfont_save, collect_font_files  # noqa: E402

# Suppress noisy fontTools warnings about coverage sorting
# Must be after fontTools imports
warnings.filterwarnings("ignore", message=".*Coverage.*not sorted.*")
logging.getLogger("fontTools").setLevel(logging.ERROR)


def main():
    """Main entry point for coverage sorter CLI."""
    parser = argparse.ArgumentParser(
        description="Sort Coverage tables in OpenType fonts by GlyphID"
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
        help="Show what would be sorted without making changes",
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

    # Track separate counts for accurate reporting
    files_sorted = 0  # Files where coverage tables were actually sorted
    files_already_sorted = 0  # Files with coverage tables that were already sorted
    files_no_coverage = 0  # Files with no coverage tables
    error_count = 0
    total_coverage = 0
    total_sorted = 0

    for font_path in font_files:
        cs.StatusIndicator("parsing").add_message(
            f"Processing: {font_path.name}"
        ).emit()

        try:
            with TTFont(font_path, lazy=False) as font:
                try:
                    if args.dry_run:
                        total, sorted_count = sort_coverage_tables_in_font(
                            font, verbose=args.verbose
                        )
                        if sorted_count > 0:
                            cs.StatusIndicator("info").add_message(
                                f"Would sort {sorted_count} of {total} Coverage table(s)"
                            ).emit()
                        elif total > 0:
                            cs.StatusIndicator("unchanged").add_message(
                                f"All {total} Coverage table(s) already sorted (no changes needed)"
                            ).emit()
                        else:
                            cs.StatusIndicator("warning").add_message(
                                "No Coverage tables found (font has no GSUB/GPOS/GDEF tables)"
                            ).emit()
                    else:
                        total, sorted_count = sort_coverage_tables_in_font(
                            font, verbose=args.verbose
                        )
                        total_coverage += total
                        total_sorted += sorted_count

                        if total > 0:
                            try:
                                if sorted_count > 0:
                                    atomic_ttfont_save(font, font_path)
                                    cs.StatusIndicator("success").add_message(
                                        f"Sorted {sorted_count} of {total} Coverage table(s)"
                                    ).emit()
                                    files_sorted += 1
                                else:
                                    cs.StatusIndicator("unchanged").add_message(
                                        f"All {total} Coverage table(s) already sorted (no changes needed)"
                                    ).emit()
                                    files_already_sorted += 1
                            except Exception as save_error:
                                cs.StatusIndicator("error").add_message(
                                    f"Failed to save font after sorting: {save_error}"
                                ).emit()
                                error_count += 1
                        else:
                            cs.StatusIndicator("warning").add_message(
                                "No Coverage tables found (font has no GSUB/GPOS/GDEF tables)"
                            ).emit()
                            files_no_coverage += 1

                except ValueError as e:
                    cs.StatusIndicator("error").add_message(
                        f"Failed to sort Coverage tables: {e}"
                    ).emit()
                    error_count += 1
                except Exception as sort_error:
                    cs.StatusIndicator("error").add_message(
                        f"Unexpected error during sorting: {sort_error}"
                    ).emit()
                    error_count += 1

        except Exception as e:
            cs.StatusIndicator("error").add_message(
                f"Failed to process {font_path.name}: {e}"
            ).emit()
            error_count += 1

        cs.emit("")

    summary = cs.StatusIndicator("success", dry_run=args.dry_run).add_message(
        "Processing complete"
    )

    summary.add_item(f"Files analyzed: {len(font_files)}")

    if files_sorted > 0:
        summary.add_item(f"Files sorted: {files_sorted}")

    if files_already_sorted > 0:
        summary.add_item(f"Files already sorted: {files_already_sorted}")

    if files_no_coverage > 0:
        summary.add_item(f"Files with no coverage: {files_no_coverage}")

    if error_count > 0:
        summary.add_item(f"Errors: {cs.fmt_count(error_count)}")

    if total_coverage > 0:
        summary.add_indent()
        summary.add_item(f"Total Coverage tables: {total_coverage}")
        if total_sorted > 0:
            summary.add_item(f"Coverage tables sorted: {total_sorted}")

    summary.emit()

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
