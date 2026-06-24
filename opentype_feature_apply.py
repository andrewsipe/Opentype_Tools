#!/usr/bin/env python3
"""
Apply .fea feature files to fonts safely.

Validates before applying, detects conflicts, sorts Coverage tables.
Thin wrapper around fontTools.feaLib with safety features.
"""

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
from lib.feature_apply import (  # noqa: E402
    HAVE_FEALIB,
    apply_features_to_font,
    detect_feature_conflicts,
    parse_fea_file,
)
from lib.io_paths import connect_fea_path  # noqa: E402
from lib.utils import atomic_ttfont_save, backup_font, collect_font_files  # noqa: E402
from lib.validation import FontValidator  # noqa: E402


def main():
    """Main entry point for feature apply CLI."""
    parser = argparse.ArgumentParser(
        description="Apply .fea feature files to fonts safely"
    )
    parser.add_argument(
        "fonts",
        nargs="+",
        help="Font files or directories to process",
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        help="Input .fea file path (single font or shared)",
    )
    parser.add_argument(
        "--input-dir",
        type=str,
        help="Directory of per-font connect FEA files (otl_reports/)",
    )
    parser.add_argument(
        "--recursive",
        "-r",
        action="store_true",
        help="Search directories recursively",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace mode: clear existing GSUB/GPOS before applying",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Copy font to backups/Stem_NNN.ext before applying",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )

    args = parser.parse_args()

    if not HAVE_FEALIB:
        cs.StatusIndicator("error").add_message(
            "fontTools.feaLib is required but not available"
        ).with_explanation("Install fonttools package").emit()
        return 1

    if not args.input and not args.input_dir:
        cs.StatusIndicator("error").add_message(
            "Specify --input or --input-dir"
        ).emit()
        return 1

    shared_fea_content = None
    if args.input:
        fea_path = Path(args.input)
        if not fea_path.exists():
            cs.StatusIndicator("error").add_message(
                f".fea file not found: {fea_path}"
            ).emit()
            return 1
        try:
            shared_fea_content = parse_fea_file(fea_path)
        except Exception as e:
            cs.StatusIndicator("error").add_message(
                f"Failed to read .fea file: {e}"
            ).emit()
            return 1
        cs.StatusIndicator("info").add_message(
            f"Loaded .fea file: {fea_path.name}"
        ).emit()
        cs.emit("")

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

        if args.input_dir:
            fea_path = Path(args.input_dir) / f"{font_path.stem}_connect.fea"
            if not fea_path.exists():
                fea_path = connect_fea_path(font_path)
        elif shared_fea_content is not None:
            fea_path = None
            fea_content = shared_fea_content
        else:
            fea_path = connect_fea_path(font_path)

        if fea_path is not None:
            if not fea_path.exists():
                cs.StatusIndicator("warning").add_message(
                    f"No .fea file for {font_path.name}: {fea_path.name}"
                ).emit()
                cs.emit("")
                continue
            try:
                fea_content = parse_fea_file(fea_path)
            except Exception as e:
                cs.StatusIndicator("error").add_message(
                    f"Failed to read {fea_path.name}: {e}"
                ).emit()
                error_count += 1
                cs.emit("")
                continue

        try:
            with TTFont(font_path, lazy=False) as font:
                validator = FontValidator(font)
                if not validator.state.has_gdef and not validator.state.has_gsub:
                    cs.StatusIndicator("warning").add_message(
                        "Font has no GDEF or GSUB tables"
                    ).with_explanation("Will create GDEF if needed").emit()

                if not args.replace:
                    conflicts = detect_feature_conflicts(font, fea_content)
                    for conflict_msg in conflicts:
                        cs.StatusIndicator("warning").add_message(conflict_msg).emit()

                if args.dry_run:
                    cs.StatusIndicator("info", dry_run=True).add_message(
                        "Would apply features"
                    ).with_explanation(
                        f"Mode: {'replace' if args.replace else 'merge'}"
                    ).emit()
                    success_count += 1
                    cs.emit("")
                    continue

                if args.backup:
                    backup_path = backup_font(font_path)
                    rel = backup_path.relative_to(font_path.parent)
                    cs.StatusIndicator("info").add_message(
                        f"Created backup: {rel}"
                    ).emit()

                success, messages = apply_features_to_font(
                    font,
                    fea_content,
                    replace_mode=args.replace,
                    merge_mode=not args.replace,
                )

                if success:
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
                        ).emit()

                    atomic_ttfont_save(font, font_path)
                    cs.StatusIndicator("success").add_message(
                        f"Saved: {font_path.name}"
                    ).emit()

                    if args.verbose:
                        for msg in messages:
                            cs.StatusIndicator("info").add_message(msg).emit()

                    success_count += 1
                else:
                    cs.StatusIndicator("error").add_message(
                        "Failed to apply features"
                    ).emit()
                    for msg in messages:
                        cs.StatusIndicator("error").add_message(msg).emit()
                    error_count += 1

        except Exception as e:
            cs.StatusIndicator("error").add_message(
                f"Failed to process {font_path.name}: {e}"
            ).emit()
            error_count += 1

        cs.emit("")

    cs.StatusIndicator("success").add_message(
        "Processing complete"
    ).with_summary_block(updated=success_count, errors=error_count).emit()

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
