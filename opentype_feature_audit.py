#!/usr/bin/env python3
"""
Audit OpenType features and generate comprehensive .fea file.

Extracts existing features, detects inactive glyphs, and suggests new features
based on naming patterns. Output is human-readable .fea file for review and editing.
"""

import argparse
import json
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from lib.fontcore_path import ensure_fontcore_on_path  # noqa: E402

ensure_fontcore_on_path(_TOOLS_DIR)

import FontCore.core_console_styles as cs  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

from lib.analyze import analyze_font  # noqa: E402
from lib.io_paths import audit_fea_path, audit_json_path, common_parent  # noqa: E402
from lib.report_render import render_audit_fea, render_audit_json  # noqa: E402
from lib.utils import collect_font_files  # noqa: E402


def main():
    """Main entry point for feature audit CLI."""
    parser = argparse.ArgumentParser(
        description="Audit OpenType features and generate comprehensive .fea file"
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
        "--output",
        "-o",
        type=str,
        help="Output file or directory (.fea/.json). Default: otl_reports/ per font dir",
    )
    parser.add_argument(
        "--suggest",
        action="store_true",
        default=True,
        help="Include suggested features (default: True)",
    )
    parser.add_argument(
        "--no-suggest",
        dest="suggest",
        action="store_false",
        help="Don't include suggested features",
    )
    parser.add_argument(
        "--format",
        choices=["fea", "json"],
        help="Output format (auto-detected from --output extension if specified)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )

    args = parser.parse_args()

    output_path = Path(args.output) if args.output else None
    output_format = args.format
    if output_path and not output_format:
        output_format = "json" if output_path.suffix.lower() == ".json" else "fea"
    if not output_format:
        output_format = "fea"

    font_files = collect_font_files(args.fonts, recursive=args.recursive)

    if not font_files:
        cs.StatusIndicator("error").add_message("No font files found").emit()
        return 1

    if (
        len(font_files) > 1
        and output_format == "fea"
        and output_path
        and output_path.suffix.lower() == ".fea"
    ):
        cs.StatusIndicator("error").add_message(
            "Multiple fonts with single .fea --output; omit -o to use otl_reports/ per font"
        ).emit()
        return 1

    scan_root = common_parent(font_files)
    output_dir = None
    if output_path and output_path.suffix.lower() not in (".fea", ".json"):
        output_dir = output_path

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
            with TTFont(font_path, lazy=False) as font:
                audit = analyze_font(font, font_path)

                if output_format == "json":
                    if output_path and output_path.suffix.lower() == ".json":
                        if len(font_files) > 1:
                            json_path = (
                                output_path.parent / f"{font_path.stem}_audit.json"
                            )
                        else:
                            json_path = output_path
                    else:
                        json_path = audit_json_path(
                            font_path, scan_root=scan_root, output_dir=output_dir
                        )

                    json_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(render_audit_json(audit), f, indent=2)

                    cs.StatusIndicator("success").add_message(
                        f"Exported JSON audit to {json_path.name}"
                    ).emit()
                else:
                    if output_path and output_path.suffix.lower() == ".fea":
                        fea_out = output_path
                    else:
                        fea_out = audit_fea_path(
                            font_path, scan_root=scan_root, output_dir=output_dir
                        )

                    fea_out.parent.mkdir(parents=True, exist_ok=True)
                    fea_content = render_audit_fea(audit, font, suggest=args.suggest)
                    fea_out.write_text(fea_content, encoding="utf-8")

                    cs.StatusIndicator("success").add_message(
                        f"Generated .fea file: {fea_out.name}"
                    ).emit()

                    if args.verbose:
                        gaps = audit.gaps()
                        cs.StatusIndicator("info").add_message(
                            f"Found {len(audit.existing_tags)} existing features, "
                            f"{len(gaps)} feature gap(s)"
                        ).emit()

                success_count += 1

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
