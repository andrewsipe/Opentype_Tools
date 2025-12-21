#!/usr/bin/env python3
"""
Sort Coverage tables in OpenType fonts by GlyphID.

Ensures Coverage tables are sorted according to GlyphOrder, which is
required by some font processors and prevents validation warnings.
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

    success_count = 0
    error_count = 0
    total_coverage = 0
    total_sorted = 0

    for font_path in font_files:
        cs.StatusIndicator("info").add_message(f"Processing: {font_path.name}").emit()

        try:
            font = TTFont(font_path, lazy=False)

            if args.dry_run:
                # For dry-run, we still need to check if sorting is needed
                # We'll do a quick check by sorting and seeing if anything changed
                # (This is a bit inefficient but necessary for accurate dry-run)
                total, sorted_count = sort_coverage_tables_in_font(
                    font, verbose=args.verbose
                )
                if sorted_count > 0:
                    cs.StatusIndicator("info").add_message(
                        f"Would sort {sorted_count} of {total} Coverage table(s)"
                    ).emit()
                else:
                    cs.StatusIndicator("info").add_message(
                        f"All {total} Coverage table(s) already sorted"
                    ).emit()
            else:
                total, sorted_count = sort_coverage_tables_in_font(
                    font, verbose=args.verbose
                )
                total_coverage += total
                total_sorted += sorted_count

                if sorted_count > 0:
                    font.save(font_path)
                    cs.StatusIndicator("success").add_message(
                        f"Sorted {sorted_count} of {total} Coverage table(s)"
                    ).emit()
                    success_count += 1
                elif total > 0:
                    cs.StatusIndicator("info").add_message(
                        f"All {total} Coverage table(s) already sorted"
                    ).emit()
                    success_count += 1
                else:
                    cs.StatusIndicator("info").add_message(
                        "No Coverage tables found"
                    ).emit()
                    success_count += 1

            font.close()

        except Exception as e:
            cs.StatusIndicator("error").add_message(
                f"Failed to process {font_path.name}: {e}"
            ).emit()
            error_count += 1

        cs.emit("")

    # Summary
    if len(font_files) > 1:
        if not args.dry_run:
            cs.StatusIndicator("info").add_message("Processing complete").with_summary_block(
                updated=success_count, errors=error_count
            ).emit()
            if total_sorted > 0:
                cs.StatusIndicator("info").add_message(
                    f"Sorted {total_sorted} of {total_coverage} Coverage table(s) total"
                ).emit()
        else:
            cs.StatusIndicator("info").add_message(
                f"Dry run complete: {success_count} font(s) checked, {error_count} error(s)"
            ).emit()

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

