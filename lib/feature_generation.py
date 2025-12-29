"""
Feature code generation from detected glyph patterns.

Generate .fea (Feature File) code from detected glyph naming patterns.
"""

from typing import List, Optional, Tuple

from fontTools.ttLib import TTFont


class FeatureCodeGenerator:
    """Generate .fea code from detected glyph patterns."""

    @staticmethod
    def generate_liga_feature(ligatures: List[Tuple[List[str], str]]) -> str:
        """Generate liga (standard ligatures) feature code."""
        if not ligatures:
            return ""

        lines = ["feature liga {"]
        for components, lig_glyph in ligatures:
            lines.append(f"  sub {' '.join(components)} by {lig_glyph};")
        lines.append("} liga;")
        return "\n".join(lines)

    @staticmethod
    def generate_dlig_feature(ligatures: List[Tuple[List[str], str]]) -> str:
        """Generate dlig (discretionary ligatures) feature code."""
        if not ligatures:
            return ""

        lines = ["feature dlig {"]
        for components, lig_glyph in ligatures:
            lines.append(f"  sub {' '.join(components)} by {lig_glyph};")
        lines.append("} dlig;")
        return "\n".join(lines)

    @staticmethod
    def generate_substitution_feature(
        feature_tag: str, substitutions: List[Tuple[str, str]]
    ) -> str:
        """Generate a simple one-to-one substitution feature."""
        if not substitutions:
            return ""

        lines = [f"feature {feature_tag} {{"]
        for base_glyph, variant_glyph in substitutions:
            lines.append(f"  sub {base_glyph} by {variant_glyph};")
        lines.append(f"}} {feature_tag};")

        return "\n".join(lines)

    @staticmethod
    def generate_stylistic_set_feature(
        ss_num: int, substitutions: List[Tuple[str, str]]
    ) -> str:
        """Generate a stylistic set feature (ss01-ss20)."""
        if not substitutions:
            return ""

        feature_tag = f"ss{ss_num:02d}"
        lines = [f"feature {feature_tag} {{"]

        for base_glyph, variant_glyph in substitutions:
            lines.append(f"  sub {base_glyph} by {variant_glyph};")

        lines.append(f"}} {feature_tag};")

        return "\n".join(lines)

    @staticmethod
    def generate_frac_feature(
        numerators: List[Tuple[str, str]],
        denominators: List[Tuple[str, str]],
        font: TTFont,
    ) -> str:
        """Generate frac (fractions) feature code."""
        if not numerators and not denominators:
            return ""

        # Find fraction slash glyph
        glyph_order = set(font.getGlyphOrder())
        slash_glyph = None
        for name in ["fraction", "fraction_slash", "slash", "fractionbar"]:
            if name in glyph_order:
                slash_glyph = name
                break

        if not slash_glyph:
            # Try to find any slash-like glyph
            for glyph in glyph_order:
                if "slash" in glyph.lower() or "fraction" in glyph.lower():
                    slash_glyph = glyph
                    break

        lines = ["feature frac {"]
        lines.append("  # Fractions - automatic fraction formatting")

        # Build numerator/denominator mappings
        num_map = {base: variant for base, variant in numerators}
        dnom_map = {base: variant for base, variant in denominators}

        # Generate substitution rules for fraction patterns
        if slash_glyph and (num_map or dnom_map):
            # Handle numerators with slash
            if num_map:
                num_bases = list(num_map.keys())
                lines.append("  # Substitute numbers before slash with numerators")
                lines.append(
                    f"  sub [{' '.join(num_bases)}] {slash_glyph}' by {slash_glyph};"
                )
                for base in num_bases:
                    lines.append(f"  sub {base}' {slash_glyph} by {num_map[base]};")

            # Handle denominators with slash
            if dnom_map:
                dnom_bases = list(dnom_map.keys())
                lines.append("  # Substitute numbers after slash with denominators")
                for base in dnom_bases:
                    lines.append(f"  sub {slash_glyph} {base}' by {dnom_map[base]};")
        else:
            # Simple substitutions if no slash found or only one type exists
            for base, variant in numerators:
                lines.append(f"  sub {base} by {variant};")
            for base, variant in denominators:
                lines.append(f"  sub {base} by {variant};")

        lines.append("} frac;")
        return "\n".join(lines)

    @staticmethod
    def generate_sups_feature(substitutions: List[Tuple[str, str]]) -> str:
        """Generate sups (superscripts) feature code."""
        return FeatureCodeGenerator.generate_substitution_feature("sups", substitutions)

    @staticmethod
    def generate_subs_feature(substitutions: List[Tuple[str, str]]) -> str:
        """Generate subs (subscripts) feature code."""
        return FeatureCodeGenerator.generate_substitution_feature("subs", substitutions)

    @staticmethod
    def generate_ordn_feature(
        substitutions: List[Tuple[str, str]], font: Optional[TTFont] = None
    ) -> str:
        """Generate ordn (ordinals) feature code with contextual substitution."""
        if not substitutions:
            return ""

        lines = ["feature ordn {"]
        lines.append("  # Ordinals - contextual substitution after numbers")
        lines.append("  # 1st, 2nd, 3rd, 4th, etc.")

        # Build glyph classes for numbers - validate they exist in font
        if font:
            glyph_order = set(font.getGlyphOrder())
            # Try common number glyph names (with and without suffixes)
            base_numbers = [
                "zero",
                "one",
                "two",
                "three",
                "four",
                "five",
                "six",
                "seven",
                "eight",
                "nine",
            ]
            number_glyphs = []
            # Check base names first
            for num_name in base_numbers:
                if num_name in glyph_order:
                    number_glyphs.append(num_name)
                else:
                    # Try with common suffixes
                    for suffix in [".oldstyle", ".lining", ".onum", ".lnum"]:
                        candidate = num_name + suffix
                        if candidate in glyph_order:
                            number_glyphs.append(candidate)
                            break
        else:
            # Fallback to hardcoded list if no font provided
            number_glyphs = [
                "zero",
                "one",
                "two",
                "three",
                "four",
                "five",
                "six",
                "seven",
                "eight",
                "nine",
            ]

        if not number_glyphs:
            # No number glyphs found, use simple substitution
            for base, variant in substitutions:
                lines.append(f"  sub {base} by {variant};")
        else:
            # Contextual substitution: number followed by ordinal letter
            for base, variant in substitutions:
                # Common ordinal patterns: a (1st), o (2nd), n (3rd), h (4th)
                if base.lower() in ["a", "o", "n", "h", "r", "t", "s"]:
                    lines.append(
                        f"  sub [{' '.join(number_glyphs)}] {base}' by {variant};"
                    )

        lines.append("} ordn;")
        return "\n".join(lines)

    @staticmethod
    def generate_c2sc_feature(substitutions: List[Tuple[str, str]]) -> str:
        """Generate c2sc (caps to small caps) feature code."""
        if not substitutions:
            return ""

        lines = ["feature c2sc {"]
        lines.append("  # Caps to Small Caps - maps uppercase to small caps")
        for base_glyph, variant_glyph in substitutions:
            lines.append(f"  sub {base_glyph} by {variant_glyph};")
        lines.append("} c2sc;")
        return "\n".join(lines)

    @staticmethod
    def generate_salt_feature(substitutions: List[Tuple[str, str]]) -> str:
        """Generate salt (stylistic alternates) feature code."""
        return FeatureCodeGenerator.generate_substitution_feature("salt", substitutions)

    @staticmethod
    def generate_zero_feature(substitutions: List[Tuple[str, str]]) -> str:
        """Generate zero (slashed zero) feature code."""
        if not substitutions:
            return ""

        lines = ["feature zero {"]
        lines.append("  # Slashed Zero - substitutes zero with slashed variant")
        for base_glyph, variant_glyph in substitutions:
            lines.append(f"  sub {base_glyph} by {variant_glyph};")
        lines.append("} zero;")
        return "\n".join(lines)

    @staticmethod
    def generate_case_feature(
        substitutions: List[Tuple[str, str]], font: Optional[TTFont] = None
    ) -> str:
        """Generate case (case-sensitive forms) feature code with contextual substitution."""
        if not substitutions:
            return ""

        lines = ["feature case {"]
        lines.append(
            "  # Case-Sensitive Forms - substitutes when preceded by uppercase"
        )

        # Build uppercase glyph class - detect from font if available
        if font:
            glyph_order = set(font.getGlyphOrder())
            best_cmap = font.getBestCmap() or {}
            # Find uppercase letters using Unicode mapping
            uppercase = []
            for cp in range(0x0041, 0x005B):  # A-Z
                if cp in best_cmap:
                    glyph_name = best_cmap[cp]
                    if glyph_name in glyph_order:
                        uppercase.append(glyph_name)
            # Also check for common uppercase glyph name patterns
            if not uppercase:
                for glyph_name in glyph_order:
                    if len(glyph_name) == 1 and glyph_name.isupper():
                        uppercase.append(glyph_name)
                    elif glyph_name.startswith("uni") and len(glyph_name) == 7:
                        # Check if it's a capital letter (uni0041 = A)
                        try:
                            cp = int(glyph_name[3:7], 16)
                            if 0x0041 <= cp <= 0x005A:
                                uppercase.append(glyph_name)
                        except ValueError:
                            pass
        else:
            # Fallback to hardcoded list if no font provided
            uppercase = [chr(ord("A") + i) for i in range(26)]

        if uppercase:
            for base_glyph, variant_glyph in substitutions:
                # Contextual substitution: uppercase letter followed by case-sensitive glyph
                lines.append(
                    f"  sub [{' '.join(uppercase)}] {base_glyph}' by {variant_glyph};"
                )
        else:
            # No uppercase glyphs found, use simple substitution
            for base_glyph, variant_glyph in substitutions:
                lines.append(f"  sub {base_glyph} by {variant_glyph};")

        lines.append("} case;")
        return "\n".join(lines)

    @staticmethod
    def generate_titl_feature(substitutions: List[Tuple[str, str]]) -> str:
        """Generate titl (titling alternates) feature code."""
        if not substitutions:
            return ""

        lines = ["feature titl {"]
        lines.append("  # Titling Alternates - display forms for titles")
        for base_glyph, variant_glyph in substitutions:
            lines.append(f"  sub {base_glyph} by {variant_glyph};")
        lines.append("} titl;")
        return "\n".join(lines)

    @staticmethod
    def generate_numr_feature(substitutions: List[Tuple[str, str]]) -> str:
        """Generate numr (standalone numerators) feature code."""
        return FeatureCodeGenerator.generate_substitution_feature("numr", substitutions)

    @staticmethod
    def generate_dnom_feature(substitutions: List[Tuple[str, str]]) -> str:
        """Generate dnom (standalone denominators) feature code."""
        return FeatureCodeGenerator.generate_substitution_feature("dnom", substitutions)

    @staticmethod
    def generate_sinf_feature(substitutions: List[Tuple[str, str]]) -> str:
        """Generate sinf (scientific inferiors) feature code."""
        return FeatureCodeGenerator.generate_substitution_feature("sinf", substitutions)

    @staticmethod
    def generate_hist_feature(substitutions: List[Tuple[str, str]]) -> str:
        """Generate hist (historical forms) feature code."""
        return FeatureCodeGenerator.generate_substitution_feature("hist", substitutions)

    @staticmethod
    def generate_smcp_feature(substitutions: List[Tuple[str, str]]) -> str:
        """Generate smcp (small caps) feature code."""
        return FeatureCodeGenerator.generate_substitution_feature("smcp", substitutions)

    @staticmethod
    def generate_onum_feature(substitutions: List[Tuple[str, str]]) -> str:
        """Generate onum (oldstyle figures) feature code."""
        return FeatureCodeGenerator.generate_substitution_feature("onum", substitutions)

    @staticmethod
    def generate_lnum_feature(substitutions: List[Tuple[str, str]]) -> str:
        """Generate lnum (lining figures) feature code."""
        return FeatureCodeGenerator.generate_substitution_feature("lnum", substitutions)

    @staticmethod
    def generate_tnum_feature(substitutions: List[Tuple[str, str]]) -> str:
        """Generate tnum (tabular figures) feature code."""
        return FeatureCodeGenerator.generate_substitution_feature("tnum", substitutions)

    @staticmethod
    def generate_pnum_feature(substitutions: List[Tuple[str, str]]) -> str:
        """Generate pnum (proportional figures) feature code."""
        return FeatureCodeGenerator.generate_substitution_feature("pnum", substitutions)

    @staticmethod
    def generate_swsh_feature(substitutions: List[Tuple[str, str]]) -> str:
        """Generate swsh (swashes) feature code."""
        return FeatureCodeGenerator.generate_substitution_feature("swsh", substitutions)

    @staticmethod
    def generate_calt_feature(substitutions: List[Tuple[str, str]]) -> str:
        """Generate calt (contextual alternates) feature code."""
        return FeatureCodeGenerator.generate_substitution_feature("calt", substitutions)
