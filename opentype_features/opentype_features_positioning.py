"""
Positioning rule generation for OpenType GPOS features.

Handles capital spacing, fraction positioning, and kerning audit/repair.
"""

from typing import Dict, List, Optional, Set, Tuple

from fontTools.ttLib import TTFont


class BoundsPen:
    """Simple pen to calculate glyph bounds."""

    def __init__(self, glyphSet):
        self.glyphSet = glyphSet
        self.bounds = None
        self._points = []

    def moveTo(self, pt):
        self._points.append(pt)

    def lineTo(self, pt):
        self._points.append(pt)

    def curveTo(self, *points):
        self._points.extend(points)

    def qCurveTo(self, *points):
        self._points.extend(points)

    def closePath(self):
        if self._points:
            xs = [pt[0] for pt in self._points]
            ys = [pt[1] for pt in self._points]
            self.bounds = (min(xs), min(ys), max(xs), max(ys))

    def endPath(self):
        self.closePath()


class PositioningRuleGenerator:
    """Generate GPOS positioning rules for features like cpsp."""

    def __init__(self, font: TTFont):
        self.font = font
        self.upm = font["head"].unitsPerEm

    def generate_cpsp_rules(
        self, capital_glyphs: List[str], spacing_value: Optional[int] = None
    ) -> str:
        """
        Add spacing between capitals.

        Args:
            capital_glyphs: List of capital glyph names
            spacing_value: Space to add (default: 5% of UPM)

        Returns:
            Feature code string for cpsp feature
        """
        if not capital_glyphs:
            return ""

        if spacing_value is None:
            spacing_value = int(self.upm * 0.05)  # 5% of UPM

        # Build glyph class for capitals
        caps_class = f"@capitals = [{' '.join(capital_glyphs)}];"

        # Generate positioning rule
        feature_code = f"""
feature cpsp {{
    # Capital Spacing - adds space between all-caps text
    {caps_class}

    # Add spacing after each capital when followed by another capital
    pos @capitals' <{spacing_value} 0 {spacing_value} 0> @capitals;
}} cpsp;
"""

        return feature_code.strip()

    def generate_fraction_positioning(
        self,
        numerator_glyphs: List[str],
        denominator_glyphs: List[str],
        slash_glyph: str = "fraction",
    ) -> str:
        """
        Generate complete fraction feature with positioning.

        This creates the classic fraction feature that:
        1. Substitutes regular numbers with numerator forms before slash
        2. Substitutes regular numbers with denominator forms after slash
        3. Positions numerators above baseline
        4. Positions denominators below baseline

        Returns:
            Feature code string for frac feature
        """
        if not numerator_glyphs and not denominator_glyphs:
            return ""

        # Calculate positioning values (typical values)
        numerator_shift = int(self.upm * 0.35)  # Shift up
        denominator_shift = int(self.upm * -0.05)  # Shift down slightly

        # Find fraction slash glyph
        glyph_order = set(self.font.getGlyphOrder())
        if slash_glyph not in glyph_order:
            # Try to find any slash-like glyph
            for glyph in glyph_order:
                if "slash" in glyph.lower() or "fraction" in glyph.lower():
                    slash_glyph = glyph
                    break
            else:
                slash_glyph = None

        feature_parts = []
        feature_parts.append("feature frac {")
        feature_parts.append(
            "  # Fractions - automatic fraction formatting with positioning"
        )

        # Build numerator/denominator mappings
        if numerator_glyphs and slash_glyph:
            num_bases = []
            num_variants = []
            for glyph in numerator_glyphs:
                # Extract base name (remove .numr suffix)
                if glyph.endswith(".numr"):
                    base = glyph[:-5]
                    if base in glyph_order:
                        num_bases.append(base)
                        num_variants.append(glyph)

            if num_bases:
                feature_parts.append(
                    "  # Substitute numbers before slash with numerators"
                )
                feature_parts.append(
                    f"  sub [{' '.join(num_bases)}] {slash_glyph}' by {slash_glyph};"
                )
                for base, variant in zip(num_bases, num_variants):
                    feature_parts.append(f"  sub {base}' {slash_glyph} by {variant};")

                # Position numerators (shift up)
                feature_parts.append("  # Position numerators above baseline")
                feature_parts.append(
                    f"  pos [{' '.join(num_variants)}] <0 {numerator_shift} 0 0>;"
                )

        if denominator_glyphs and slash_glyph:
            dnom_bases = []
            dnom_variants = []
            for glyph in denominator_glyphs:
                # Extract base name (remove .dnom suffix)
                if glyph.endswith(".dnom"):
                    base = glyph[:-5]
                    if base in glyph_order:
                        dnom_bases.append(base)
                        dnom_variants.append(glyph)

            if dnom_bases:
                feature_parts.append(
                    "  # Substitute numbers after slash with denominators"
                )
                for base, variant in zip(dnom_bases, dnom_variants):
                    feature_parts.append(f"  sub {slash_glyph} {base}' by {variant};")

                # Position denominators (shift down)
                feature_parts.append("  # Position denominators below baseline")
                feature_parts.append(
                    f"  pos [{' '.join(dnom_variants)}] <0 {denominator_shift} 0 0>;"
                )

        feature_parts.append("} frac;")
        return "\n".join(feature_parts)

    def validate_kern_table(self, font: TTFont) -> Dict:
        """
        Audit existing kerning for common issues.

        Returns:
            dict with validation results
        """
        issues = {
            "missing_pairs": [],
            "extreme_values": [],
            "duplicate_pairs": [],
            "legacy_kern_table": False,
        }

        # Check for legacy kern table
        if "kern" in font:
            issues["legacy_kern_table"] = True

        # Validate GPOS kern feature if it exists
        if "GPOS" in font:
            gpos = font["GPOS"]

            # Extract kern pairs from GPOS
            kern_pairs = self._extract_gpos_pairs(gpos)

            # Check for extreme values (likely errors)
            for (left, right), value in kern_pairs.items():
                if abs(value) > self.upm * 0.5:  # 50% of UPM is extreme
                    issues["extreme_values"].append(
                        {"pair": (left, right), "value": value}
                    )

            # Check for common missing pairs
            critical_pairs = [
                ("A", "V"),
                ("A", "W"),
                ("T", "o"),
                ("V", "A"),
                ("W", "A"),
                ("Y", "o"),
                ("F", "o"),
            ]

            glyph_order = set(font.getGlyphOrder())
            for pair in critical_pairs:
                if pair not in kern_pairs and all(g in glyph_order for g in pair):
                    issues["missing_pairs"].append(pair)

        return issues

    def _extract_gpos_pairs(self, gpos_table) -> Dict[Tuple[str, str], int]:
        """Extract kerning pairs from GPOS table."""
        kern_pairs = {}

        # This is simplified - real implementation would need to
        # traverse the GPOS lookup structure
        try:
            if hasattr(gpos_table, "table") and hasattr(gpos_table.table, "LookupList"):
                lookup_list = gpos_table.table.LookupList
                if lookup_list and hasattr(lookup_list, "Lookup"):
                    for lookup in lookup_list.Lookup:
                        if lookup.LookupType == 2:  # Pair adjustment
                            if hasattr(lookup, "SubTable"):
                                for subtable in lookup.SubTable:
                                    # Extract pairs from subtable
                                    # (Implementation depends on GPOS structure)
                                    if hasattr(subtable, "PairSets"):
                                        # Format 1: PairSets
                                        pass
                                    elif hasattr(subtable, "ClassDef1"):
                                        # Format 2: Class-based
                                        pass
        except (AttributeError, TypeError):
            pass

        return kern_pairs

    def repair_kern_table(self, issues: Dict, auto_add_values: bool = True) -> str:
        """
        Repair kerning issues.

        Args:
            issues: Dictionary from validate_kern_table()
            auto_add_values: If True, calculate and add missing pairs

        Returns:
            Feature code to add/fix kerning
        """
        feature_code_parts = []

        if issues.get("missing_pairs") and auto_add_values:
            # Add common kern pairs with calculated values
            feature_code_parts.append("# Auto-generated kern pairs")

            for left, right in issues["missing_pairs"]:
                # Calculate appropriate kerning based on glyph metrics
                kern_value = self._calculate_kern_value(left, right)
                if kern_value != 0:
                    feature_code_parts.append(f"pos {left} {right} {kern_value};")

        if feature_code_parts:
            return f"""
feature kern {{
    {chr(10).join(feature_code_parts)}
}} kern;
""".strip()

        return ""

    def _calculate_kern_value(self, left_glyph: str, right_glyph: str) -> int:
        """
        Calculate appropriate kerning between two glyphs.
        Uses bounding box analysis.
        """
        try:
            glyph_set = self.font.getGlyphSet()
            left_pen = BoundsPen(glyph_set)
            right_pen = BoundsPen(glyph_set)

            if left_glyph in glyph_set:
                glyph_set[left_glyph].draw(left_pen)
            if right_glyph in glyph_set:
                glyph_set[right_glyph].draw(right_pen)

            left_bounds = left_pen.bounds
            right_bounds = right_pen.bounds

            if left_bounds and right_bounds:
                # Calculate overlap/gap
                left_right_edge = left_bounds[2]  # xMax of left glyph
                right_left_edge = right_bounds[0]  # xMin of right glyph

                gap = right_left_edge - left_right_edge

                # If glyphs are too far apart, bring them closer
                # This is a simplified heuristic
                if gap > self.upm * 0.15:
                    return -int(gap * 0.3)
                elif gap < 0:  # Overlapping
                    return int(abs(gap) * 0.5)

        except Exception:
            pass

        return 0

    def _get_glyph_bounds(self, glyph_name: str) -> Optional[Tuple[int, int, int, int]]:
        """Calculate bounding box for a glyph."""
        try:
            glyph_set = self.font.getGlyphSet()
            pen = BoundsPen(glyph_set)
            if glyph_name in glyph_set:
                glyph_set[glyph_name].draw(pen)
                return pen.bounds
        except Exception:
            pass
        return None
