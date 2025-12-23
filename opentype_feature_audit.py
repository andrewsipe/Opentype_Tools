#!/usr/bin/env python3
"""
Audit OpenType features and generate comprehensive .fea file.

Extracts existing features, detects inactive glyphs, and suggests new features
based on naming patterns. Output is human-readable .fea file for review and editing.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set

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

from lib.detection import UnifiedGlyphDetector  # noqa: E402
from lib.feature_extraction import (  # noqa: E402
    ExistingSubstitutionExtractor,
    FeatureExtractor,
)
from lib.feature_generation import FeatureCodeGenerator  # noqa: E402
from lib.utils import collect_font_files  # noqa: E402


def get_existing_feature_tags(font: TTFont) -> Set[str]:
    """Get set of existing feature tags from font."""
    existing = set()

    # GSUB features
    if "GSUB" in font:
        gsub = font["GSUB"].table
        if hasattr(gsub, "FeatureList") and gsub.FeatureList:
            for frec in gsub.FeatureList.FeatureRecord:
                existing.add(frec.FeatureTag)

    # GPOS features
    if "GPOS" in font:
        gpos = font["GPOS"].table
        if hasattr(gpos, "FeatureList") and gpos.FeatureList:
            for frec in gpos.FeatureList.FeatureRecord:
                existing.add(frec.FeatureTag)

    return existing


def generate_audit_fea(
    font: TTFont,
    extractor: FeatureExtractor,
    detector: UnifiedGlyphDetector,
    existing_extractor: ExistingSubstitutionExtractor,
    suggest: bool = True,
) -> str:
    """Generate comprehensive .fea file with active, inactive, and suggested features."""
    sections = []

    # Section 1: ACTIVE FEATURES
    active_fea = extractor.extract_all_features_as_fea()
    if active_fea:
        sections.append("# " + "=" * 50)
        sections.append("# EXISTING ACTIVE FEATURES")
        sections.append(
            f"# Extracted from font on {datetime.now().strftime('%Y-%m-%d')}"
        )
        sections.append("# " + "=" * 50)
        sections.append("")
        sections.append(active_fea)
        sections.append("")

    # Get existing features and substitutions
    existing_tags = get_existing_feature_tags(font)
    existing_subs = existing_extractor.extract_all()

    # Get detected patterns
    detected = detector.get_features()

    # Section 2: INACTIVE FEATURES (glyphs exist but not activated)
    inactive_features = []
    detected_ss = detected.get("stylistic_sets", {})

    for ss_num, substitutions in sorted(detected_ss.items()):
        if 1 <= ss_num <= 20:
            feature_tag = f"ss{ss_num:02d}"
            if feature_tag not in existing_tags:
                # Check if any of these substitutions already exist
                new_subs = []
                for base, alt in substitutions:
                    if (base, alt) not in existing_subs["single"]:
                        new_subs.append((base, alt))

                if new_subs:
                    fea_code = FeatureCodeGenerator.generate_stylistic_set_feature(
                        ss_num, new_subs
                    )
                    inactive_features.append((feature_tag, len(new_subs), fea_code))

    if inactive_features:
        sections.append("# " + "=" * 50)
        sections.append("# INACTIVE FEATURES")
        sections.append("# Glyphs exist but features are not activated")
        sections.append("# Uncomment blocks below to enable")
        sections.append("# " + "=" * 50)
        sections.append("")

        for feature_tag, count, fea_code in inactive_features:
            # Extract sample glyphs for comment
            lines = fea_code.split("\n")
            sample_glyphs = []
            for line in lines:
                if "sub " in line and "by" in line:
                    parts = line.split("by")
                    if len(parts) == 2:
                        left = parts[0].replace("sub", "").strip()
                        right = parts[1].replace(";", "").strip()
                        if " " not in left:  # Single substitution
                            sample_glyphs.append(f"{left}→{right}")
                            if len(sample_glyphs) >= 3:
                                break

            sample_str = ", ".join(sample_glyphs)
            if count > 3:
                sample_str += f" ({count - 3} more)"

            sections.append(f"# {feature_tag.upper()}: {count} glyphs")
            sections.append(f"# Detected glyphs: {sample_str}")
            sections.append("")
            # Comment out the feature code
            for line in fea_code.split("\n"):
                sections.append(f"# {line}")
            sections.append("")

    # Section 3: SUGGESTED FEATURES (based on naming patterns)
    if suggest:
        suggested_features = []

        # Map feature tags to generation methods
        feature_map = {
            "liga": (
                "Standard Ligatures",
                lambda: FeatureCodeGenerator.generate_liga_feature(
                    detected.get("liga", [])
                ),
            ),
            "dlig": (
                "Discretionary Ligatures",
                lambda: FeatureCodeGenerator.generate_dlig_feature(
                    detected.get("dlig", [])
                ),
            ),
            "smcp": (
                "Small Caps",
                lambda: FeatureCodeGenerator.generate_smcp_feature(
                    detected.get("smcp", [])
                ),
            ),
            "onum": (
                "Oldstyle Figures",
                lambda: FeatureCodeGenerator.generate_onum_feature(
                    detected.get("onum", [])
                ),
            ),
            "lnum": (
                "Lining Figures",
                lambda: FeatureCodeGenerator.generate_lnum_feature(
                    detected.get("lnum", [])
                ),
            ),
            "tnum": (
                "Tabular Figures",
                lambda: FeatureCodeGenerator.generate_tnum_feature(
                    detected.get("tnum", [])
                ),
            ),
            "pnum": (
                "Proportional Figures",
                lambda: FeatureCodeGenerator.generate_pnum_feature(
                    detected.get("pnum", [])
                ),
            ),
            "swsh": (
                "Swashes",
                lambda: FeatureCodeGenerator.generate_swsh_feature(
                    detected.get("swsh", [])
                ),
            ),
            "calt": (
                "Contextual Alternates",
                lambda: FeatureCodeGenerator.generate_calt_feature(
                    detected.get("calt", [])
                ),
            ),
            "frac": (
                "Fractions",
                lambda: FeatureCodeGenerator.generate_frac_feature(
                    detected.get("frac", {}).get("numerators", []),
                    detected.get("frac", {}).get("denominators", []),
                    font,
                ),
            ),
            "sups": (
                "Superscripts",
                lambda: FeatureCodeGenerator.generate_sups_feature(
                    detected.get("sups", [])
                ),
            ),
            "subs": (
                "Subscripts",
                lambda: FeatureCodeGenerator.generate_subs_feature(
                    detected.get("subs", [])
                ),
            ),
            "ordn": (
                "Ordinals",
                lambda: FeatureCodeGenerator.generate_ordn_feature(
                    detected.get("ordn", []), font
                ),
            ),
            "c2sc": (
                "Caps to Small Caps",
                lambda: FeatureCodeGenerator.generate_c2sc_feature(
                    detected.get("c2sc", [])
                ),
            ),
            "salt": (
                "Stylistic Alternates",
                lambda: FeatureCodeGenerator.generate_salt_feature(
                    detected.get("salt", [])
                ),
            ),
            "zero": (
                "Slashed Zero",
                lambda: FeatureCodeGenerator.generate_zero_feature(
                    detected.get("zero", [])
                ),
            ),
            "case": (
                "Case-Sensitive Forms",
                lambda: FeatureCodeGenerator.generate_case_feature(
                    detected.get("case", []), font
                ),
            ),
            "titl": (
                "Titling Alternates",
                lambda: FeatureCodeGenerator.generate_titl_feature(
                    detected.get("titl", [])
                ),
            ),
        }

        for feature_tag, (description, generator_func) in feature_map.items():
            if feature_tag not in existing_tags:
                fea_code = generator_func()
                if fea_code:
                    # Count substitutions in the generated code
                    count = fea_code.count("sub ") or fea_code.count("pos ")
                    suggested_features.append(
                        (feature_tag, description, count, fea_code)
                    )

        if suggested_features:
            sections.append("# " + "=" * 50)
            sections.append("# SUGGESTED FEATURES")
            sections.append("# Based on glyph naming patterns")
            sections.append("# Review carefully before uncommenting")
            sections.append("# " + "=" * 50)
            sections.append("")

            for feature_tag, description, count, fea_code in suggested_features:
                # Extract sample glyphs for comment
                lines = fea_code.split("\n")
                sample_glyphs = []
                for line in lines:
                    if "sub " in line and "by" in line:
                        parts = line.split("by")
                        if len(parts) == 2:
                            left = parts[0].replace("sub", "").strip()
                            right = parts[1].replace(";", "").strip()
                            if " " not in left:  # Single substitution
                                sample_glyphs.append(f"{left}→{right}")
                                if len(sample_glyphs) >= 3:
                                    break

                sample_str = ", ".join(sample_glyphs)
                if count > 3:
                    sample_str += f" ({count - 3} more)"

                sections.append(f"# {description} ({count} glyphs)")
                sections.append(f"# Detected glyphs: {sample_str}")
                sections.append("")
                # Comment out the feature code
                for line in fea_code.split("\n"):
                    sections.append(f"# {line}")
                sections.append("")

    return "\n".join(sections)


def generate_audit_json(
    font: TTFont,
    extractor: FeatureExtractor,
    detector: UnifiedGlyphDetector,
    existing_extractor: ExistingSubstitutionExtractor,
) -> Dict:
    """Generate JSON audit report."""
    existing_tags = get_existing_feature_tags(font)
    detected = detector.get_features()
    existing_subs = existing_extractor.extract_all()

    audit = {
        "font": str(font.reader.file.name) if hasattr(font, "reader") else "unknown",
        "timestamp": datetime.now().isoformat(),
        "existing_features": sorted(list(existing_tags)),
        "active_features": {},
        "inactive_features": [],
        "suggested_features": [],
    }

    # Extract active features
    active_fea = extractor.extract_all_features_as_fea()
    if active_fea:
        audit["active_features"]["fea_code"] = active_fea

    # Find inactive features
    detected_ss = detected.get("stylistic_sets", {})
    for ss_num, substitutions in sorted(detected_ss.items()):
        if 1 <= ss_num <= 20:
            feature_tag = f"ss{ss_num:02d}"
            if feature_tag not in existing_tags:
                new_subs = [
                    (base, alt)
                    for base, alt in substitutions
                    if (base, alt) not in existing_subs["single"]
                ]
                if new_subs:
                    audit["inactive_features"].append(
                        {
                            "tag": feature_tag,
                            "type": "stylistic_set",
                            "glyph_count": len(new_subs),
                            "substitutions": new_subs[:10],  # First 10
                        }
                    )

    # Find suggested features
    feature_counts = {
        "liga": len(detected.get("liga", [])),
        "dlig": len(detected.get("dlig", [])),
        "smcp": len(detected.get("smcp", [])),
        "onum": len(detected.get("onum", [])),
        "lnum": len(detected.get("lnum", [])),
        "tnum": len(detected.get("tnum", [])),
        "pnum": len(detected.get("pnum", [])),
        "swsh": len(detected.get("swsh", [])),
        "calt": len(detected.get("calt", [])),
    }

    for tag, count in feature_counts.items():
        if tag not in existing_tags and count > 0:
            audit["suggested_features"].append({"tag": tag, "glyph_count": count})

    return audit


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
        required=True,
        help="Output file path (.fea or .json)",
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
        help="Output format (auto-detected from --output extension if not specified)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )

    args = parser.parse_args()

    # Determine output format
    output_path = Path(args.output)
    if args.format:
        output_format = args.format
    else:
        if output_path.suffix.lower() == ".json":
            output_format = "json"
        else:
            output_format = "fea"

    # Collect font files
    font_files = collect_font_files(args.fonts, recursive=args.recursive)

    if not font_files:
        cs.StatusIndicator("error").add_message("No font files found").emit()
        return 1

    if len(font_files) > 1 and output_format == "fea":
        cs.StatusIndicator("error").add_message(
            "Multiple fonts specified but .fea output only supports single font"
        ).emit()
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

            # Initialize extractors and detector
            extractor = FeatureExtractor(font)
            detector = UnifiedGlyphDetector(font)
            existing_extractor = ExistingSubstitutionExtractor(font)

            if output_format == "json":
                audit_data = generate_audit_json(
                    font, extractor, detector, existing_extractor
                )
                audit_data["font"] = str(font_path)

                # For multiple fonts, append to list or create separate files
                if len(font_files) > 1:
                    json_path = output_path.parent / f"{font_path.stem}_audit.json"
                else:
                    json_path = output_path

                with open(json_path, "w") as f:
                    json.dump(audit_data, f, indent=2)

                cs.StatusIndicator("success").add_message(
                    f"Exported JSON audit to {json_path.name}"
                ).emit()

            else:  # fea format
                fea_content = generate_audit_fea(
                    font,
                    extractor,
                    detector,
                    existing_extractor,
                    suggest=args.suggest,
                )

                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(fea_content)

                cs.StatusIndicator("success").add_message(
                    f"Generated .fea file: {output_path.name}"
                ).emit()

                if args.verbose:
                    existing_tags = get_existing_feature_tags(font)
                    detected = detector.get_features()
                    cs.StatusIndicator("info").add_message(
                        f"Found {len(existing_tags)} existing features, "
                        f"{sum(len(v) if isinstance(v, list) else 1 for v in detected.values() if v)} detected patterns"
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
