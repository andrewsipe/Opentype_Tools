#!/usr/bin/env python3
"""
Repair stylistic set metadata: FeatureParams, UINameIDs, name table labels.

Does NOT modify GSUB substitutions - only fixes metadata.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
from fontTools.ttLib.tables import otTables  # noqa: E402

from lib.detection import UnifiedGlyphDetector  # noqa: E402
from lib.ss_labeler import SSLabeler  # noqa: E402
from lib.utils import collect_font_files  # noqa: E402


def collect_ss_features(font: TTFont) -> Dict[int, List]:
    """Collect stylistic set features (ss01-ss20) from GSUB."""
    ss_groups = {}

    if "GSUB" not in font:
        return ss_groups

    gsub = font["GSUB"].table
    if not hasattr(gsub, "FeatureList") or not gsub.FeatureList:
        return ss_groups

    for frec in gsub.FeatureList.FeatureRecord:
        tag = frec.FeatureTag
        if tag.startswith("ss") and len(tag) == 4:
            try:
                ss_num = int(tag[2:])
                if 1 <= ss_num <= 20:
                    ss_groups.setdefault(ss_num, []).append(frec)
            except ValueError:
                continue

    return ss_groups


def extract_ss_glyphs(font: TTFont, ss_num: int) -> List[Tuple[str, str]]:
    """Extract glyph substitutions for a stylistic set."""
    glyphs = []

    if "GSUB" not in font:
        return glyphs

    gsub = font["GSUB"].table
    if not hasattr(gsub, "FeatureList") or not gsub.FeatureList:
        return glyphs

    # Find the ss feature
    feature = None
    for frec in gsub.FeatureList.FeatureRecord:
        if frec.FeatureTag == f"ss{ss_num:02d}":
            feature = frec.Feature
            break

    if not feature:
        return glyphs

    # Extract substitutions from lookups
    if hasattr(gsub, "LookupList") and gsub.LookupList:
        for lookup_idx in feature.LookupListIndex:
            if lookup_idx < len(gsub.LookupList.Lookup):
                lookup = gsub.LookupList.Lookup[lookup_idx]
                if lookup.LookupType == 1:  # Single substitution
                    for subtable in lookup.SubTable:
                        if hasattr(subtable, "mapping"):
                            for base, alternate in subtable.mapping.items():
                                glyphs.append((base, alternate))

    return glyphs


def audit_ss_features(font: TTFont, labeler: SSLabeler) -> List[Dict]:
    """Audit stylistic set features and return issues."""
    issues = []
    ss_groups = collect_ss_features(font)

    for ss_num, records in sorted(ss_groups.items()):
        issue = {
            "ss_num": ss_num,
            "glyph_count": 0,
            "missing_params": False,
            "missing_uinameid": False,
            "missing_label": False,
            "generic_label": False,
            "current_label": None,
            "suggested_label": None,
            "confidence": 0.0,
            "glyphs": [],
        }

        # Extract glyphs
        glyphs = extract_ss_glyphs(font, ss_num)
        issue["glyph_count"] = len(glyphs)
        issue["glyphs"] = glyphs[:10]  # First 10 for display

        # Check FeatureParams
        has_params = False
        has_uinameid = False
        uinameid = None

        for frec in records:
            feature = frec.Feature
            params = getattr(feature, "FeatureParams", None)
            if params is not None:
                has_params = True
                uinameid = getattr(params, "UINameID", None)
                if uinameid is not None:
                    has_uinameid = True
                    break

        issue["missing_params"] = not has_params
        issue["missing_uinameid"] = not has_uinameid

        # Check name table label
        if uinameid is not None:
            if "name" in font:
                name_table = font["name"]
                label = None
                for record in name_table.names:
                    if record.nameID == uinameid:
                        label = record.toUnicode()
                        break

                issue["current_label"] = label
                if label is None:
                    issue["missing_label"] = True
                elif label == f"Stylistic Set {ss_num:02d}":
                    issue["generic_label"] = True

        # Generate suggestion
        if glyphs:
            suggested, confidence = labeler.suggest_label(ss_num, glyphs)
            issue["suggested_label"] = suggested
            issue["confidence"] = confidence

        issues.append(issue)

    return issues


def main():
    """Main entry point for SS repair CLI."""
    parser = argparse.ArgumentParser(
        description="Repair stylistic set metadata (FeatureParams, UINameIDs, name table labels)"
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
        "--audit",
        action="store_true",
        help="Audit only (read-only, safe)",
    )
    parser.add_argument(
        "--auto-fix",
        action="store_true",
        help="Auto-fix high confidence issues (0.75+)",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.75,
        help="Minimum confidence for auto-fix (default: 0.75)",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Interactive mode (confirm each change)",
    )
    parser.add_argument(
        "--export",
        type=str,
        help="Export suggestions to JSON file",
    )
    parser.add_argument(
        "--import",
        dest="import_file",
        type=str,
        help="Import labels from JSON file",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes from imported JSON",
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

    # Handle export mode
    if args.export and len(font_files) == 1:
        try:
            font = TTFont(font_files[0], lazy=False)
            labeler = SSLabeler(font)
            issues = audit_ss_features(font, labeler)

            export_data = {
                "font": str(font_files[0]),
                "issues": issues,
            }

            with open(args.export, "w") as f:
                json.dump(export_data, f, indent=2)

            cs.StatusIndicator("success").add_message(
                f"Exported suggestions to {args.export}"
            ).emit()
            font.close()
            return 0
        except Exception as e:
            cs.StatusIndicator("error").add_message(f"Export failed: {e}").emit()
            return 1

    # Handle import/apply mode
    if args.import_file and args.apply:
        cs.StatusIndicator("error").add_message(
            "Import/apply mode not yet implemented"
        ).emit()
        return 1

    # Process fonts
    success_count = 0
    error_count = 0

    for font_path in font_files:
        cs.StatusIndicator("parsing").add_message(
            f"Processing: {font_path.name}"
        ).emit()

        try:
            font = TTFont(font_path, lazy=False)
            labeler = SSLabeler(font)
            issues = audit_ss_features(font, labeler)

            if not issues:
                cs.StatusIndicator("info").add_message(
                    "No ss01-ss20 features found"
                ).emit()
                font.close()
                success_count += 1
                cs.emit("")
                continue

            # Display audit results
            for issue in issues:
                ss_num = issue["ss_num"]
                glyph_count = issue["glyph_count"]
                suggested = issue["suggested_label"]
                confidence = issue["confidence"]

                # Build status indicator with details
                indicator = cs.StatusIndicator("info").add_message(
                    f"ss{ss_num:02d}: {cs.fmt_count(glyph_count)} glyphs → '{suggested}' ({confidence:.2f})"
                )
                
                # Add status details as items
                if issue["missing_params"]:
                    indicator.add_item("No FeatureParams", style="dim red")
                if issue["missing_uinameid"]:
                    indicator.add_item("No UINameID", style="dim red")
                if issue["missing_label"]:
                    indicator.add_item("No label", style="dim red")
                if issue["generic_label"]:
                    indicator.add_item("Generic label", style="dim yellow")
                if not any([issue["missing_params"], issue["missing_uinameid"], 
                           issue["missing_label"], issue["generic_label"]]):
                    indicator.add_item("OK", style="dim green")
                
                indicator.emit()

                if args.verbose and issue["glyphs"]:
                    sample_glyphs = ", ".join(
                        [f"{base} → {alt}" for base, alt in issue["glyphs"][:5]]
                    )
                    cs.StatusIndicator("info").add_message(
                        f"  Sample: {sample_glyphs}"
                    ).emit()

            # Auto-fix mode
            if args.auto_fix:
                changes_made = False
                for issue in issues:
                    if issue["confidence"] >= args.min_confidence:
                        # TODO: Implement actual fixing
                        cs.StatusIndicator("info").add_message(
                            f"Would fix ss{issue['ss_num']:02d} (confidence {issue['confidence']:.2f})"
                        ).emit()
                        changes_made = True

                if changes_made:
                    cs.StatusIndicator("warning").add_message(
                        "Auto-fix not yet fully implemented"
                    ).emit()

            font.close()
            success_count += 1

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
