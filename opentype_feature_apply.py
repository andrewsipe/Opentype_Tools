#!/usr/bin/env python3
"""
Apply .fea feature files to fonts safely.

Validates before applying, detects conflicts, sorts Coverage tables.
Thin wrapper around fontTools.feaLib with safety features.
"""

import argparse
import sys
from pathlib import Path
from typing import List

# Add project root to path for FontCore imports
_project_root = Path(__file__).parent
while (
    not (_project_root / "FontCore").exists() and _project_root.parent != _project_root
):
    _project_root = _project_root.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import FontCore.core_console_styles as cs  # noqa: E402
from fontTools.ttLib import TTFont, newTable  # noqa: E402
from fontTools.ttLib.tables import otTables  # noqa: E402

from lib.coverage import sort_coverage_tables_in_font  # noqa: E402
from lib.utils import backup_font, collect_font_files  # noqa: E402
from lib.validation import FontValidator  # noqa: E402

try:
    from fontTools.feaLib.builder import addOpenTypeFeaturesFromString

    HAVE_FEALIB = True
except Exception:
    HAVE_FEALIB = False
    addOpenTypeFeaturesFromString = None


def parse_fea_file(fea_path: Path) -> str:
    """Read and parse .fea file."""
    try:
        with open(fea_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        raise ValueError(f"Failed to read .fea file: {e}")


def detect_feature_conflicts(font: TTFont, fea_content: str) -> List[str]:
    """
    Detect potential conflicts between existing features and .fea file.

    Returns list of warning messages.
    """
    warnings = []

    # Extract feature tags from .fea file (simple regex-based extraction)
    import re

    fea_tags = set()
    for match in re.finditer(r"feature\s+(\w+)\s*\{", fea_content):
        fea_tags.add(match.group(1))

    # Get existing feature tags
    existing_tags = set()

    if "GSUB" in font:
        gsub = font["GSUB"].table
        if hasattr(gsub, "FeatureList") and gsub.FeatureList:
            for frec in gsub.FeatureList.FeatureRecord:
                existing_tags.add(frec.FeatureTag)

    if "GPOS" in font:
        gpos = font["GPOS"].table
        if hasattr(gpos, "FeatureList") and gpos.FeatureList:
            for frec in gpos.FeatureList.FeatureRecord:
                existing_tags.add(frec.FeatureTag)

    # Check for conflicts
    conflicts = fea_tags.intersection(existing_tags)
    if conflicts:
        warnings.append(
            f"Features already exist: {', '.join(sorted(conflicts))}. "
            "They will be merged/replaced depending on mode."
        )

    return warnings


def apply_features_to_font(
    font: TTFont,
    fea_content: str,
    replace_mode: bool = False,
    verbose: bool = False,
) -> tuple[bool, list[str]]:
    """
    Apply .fea content to font.

    Returns: (success, messages)
    """
    messages = []

    if not HAVE_FEALIB:
        return False, ["fontTools.feaLib is required but not available"]

    # Ensure GDEF exists (required for features)
    if "GDEF" not in font:
        gdef = newTable("GDEF")
        gdef.table = otTables.GDEF()
        gdef.table.Version = 0x00010000
        gdef.table.GlyphClassDef = None
        gdef.table.AttachList = None
        gdef.table.LigCaretList = None
        gdef.table.MarkAttachClassDef = None
        gdef.table.MarkGlyphSetsDef = None
        font["GDEF"] = gdef
        messages.append("Created GDEF table (required for features)")

    # In replace mode, clear existing GSUB/GPOS
    if replace_mode:
        # Helper function to create empty OTL table
        def _empty_otl_table(table_cls: type) -> object:
            """Create empty OTL table structure."""
            tbl = table_cls()
            tbl.Version = 0x00010000
            sl = otTables.ScriptList()
            sl.ScriptCount = 0
            sl.ScriptRecord = []
            fl = otTables.FeatureList()
            fl.FeatureCount = 0
            fl.FeatureRecord = []
            ll = otTables.LookupList()
            ll.LookupCount = 0
            ll.Lookup = []
            tbl.ScriptList = sl
            tbl.FeatureList = fl
            tbl.LookupList = ll
            return tbl

        if "GSUB" in font:
            gsub = font["GSUB"].table
            if hasattr(gsub, "LookupList") and gsub.LookupList:
                lookup_count = len(gsub.LookupList.Lookup)
                if lookup_count > 0:
                    # Create empty GSUB
                    gsub_new = newTable("GSUB")
                    gsub_new.table = _empty_otl_table(otTables.GSUB)
                    font["GSUB"] = gsub_new
                    messages.append(f"Cleared GSUB ({lookup_count} lookups removed)")

        if "GPOS" in font:
            gpos = font["GPOS"].table
            if hasattr(gpos, "LookupList") and gpos.LookupList:
                lookup_count = len(gpos.LookupList.Lookup)
                if lookup_count > 0:
                    # Create empty GPOS
                    gpos_new = newTable("GPOS")
                    gpos_new.table = _empty_otl_table(otTables.GPOS)
                    font["GPOS"] = gpos_new
                    messages.append(f"Cleared GPOS ({lookup_count} lookups removed)")

    # Apply features
    try:
        addOpenTypeFeaturesFromString(font, fea_content)
        messages.append("Features compiled and applied successfully")
        return True, messages
    except Exception as e:
        return False, [f"Failed to compile features: {e}"]


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
        required=True,
        help="Input .fea file path",
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
        help="Create backup before applying",
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

    # Read .fea file
    fea_path = Path(args.input)
    if not fea_path.exists():
        cs.StatusIndicator("error").add_message(f".fea file not found: {fea_path}").emit()
        return 1

    try:
        fea_content = parse_fea_file(fea_path)
    except Exception as e:
        cs.StatusIndicator("error").add_message(f"Failed to read .fea file: {e}").emit()
        return 1

    cs.StatusIndicator("info").add_message(f"Loaded .fea file: {fea_path.name}").emit()
    cs.emit("")

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

            # Validate font state
            validator = FontValidator(font)
            if not validator.state.has_gdef and not validator.state.has_gsub:
                cs.StatusIndicator("warning").add_message(
                    "Font has no GDEF or GSUB tables"
                ).with_explanation("Will create GDEF if needed").emit()

            # Detect conflicts
            if not args.replace:
                conflicts = detect_feature_conflicts(font, fea_content)
                for conflict_msg in conflicts:
                    cs.StatusIndicator("warning").add_message(conflict_msg).emit()

            if args.dry_run:
                cs.StatusIndicator("info").add_message(
                    "DRY RUN - would apply features"
                ).with_explanation(
                    f"Mode: {'replace' if args.replace else 'merge'}"
                ).emit()
                font.close()
                success_count += 1
                cs.emit("")
                continue

            # Create backup if requested
            if args.backup:
                backup_path = backup_font(font_path)
                cs.StatusIndicator("info").add_message(
                    f"Created backup: {backup_path.name}"
                ).emit()

            # Apply features
            success, messages = apply_features_to_font(
                font, fea_content, replace_mode=args.replace, verbose=args.verbose
            )

            if success:
                # Sort Coverage tables
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

                # Save font
                font.save(font_path)
                cs.StatusIndicator("success").add_message(
                    f"Saved: {font_path.name}"
                ).emit()

                if args.verbose:
                    for msg in messages:
                        cs.StatusIndicator("info").add_message(msg).emit()

                success_count += 1
            else:
                cs.StatusIndicator("error").add_message("Failed to apply features").emit()
                for msg in messages:
                    cs.StatusIndicator("error").add_message(msg).emit()
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

