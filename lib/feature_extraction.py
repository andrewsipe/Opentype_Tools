"""
Feature extraction from OpenType fonts.

Extract existing OpenType features from fonts as .fea code and identify
existing substitutions to avoid duplicates.
"""

from typing import Dict, List, Set, Tuple

from fontTools.ttLib import TTFont


class FeatureExtractor:
    """Extract existing OpenType features from font as .fea code."""

    def __init__(self, font: TTFont):
        self.font = font

    def extract_gsub_features_as_fea(self) -> str:
        """Extract existing GSUB features as FEA code."""
        if "GSUB" not in self.font:
            return ""

        gsub = self.font["GSUB"].table
        if not hasattr(gsub, "FeatureList") or not gsub.FeatureList:
            return ""

        feature_blocks = []

        # Process each feature
        for frec in gsub.FeatureList.FeatureRecord:
            feature_tag = frec.FeatureTag
            feature = frec.Feature

            # Get lookup indices for this feature
            lookup_indices = (
                feature.LookupListIndex if hasattr(feature, "LookupListIndex") else []
            )

            if not lookup_indices:
                continue

            # Extract substitution rules from lookups
            rules = []
            for lookup_idx in lookup_indices:
                if lookup_idx >= len(gsub.LookupList.Lookup):
                    continue

                lookup = gsub.LookupList.Lookup[lookup_idx]
                lookup_rules = self._extract_lookup_rules(lookup)
                rules.extend(lookup_rules)

            if rules:
                # Build feature block
                fea_lines = [f"feature {feature_tag} {{"]
                fea_lines.extend([f"  {rule}" for rule in rules])
                fea_lines.append(f"}} {feature_tag};")
                feature_blocks.append("\n".join(fea_lines))

        return "\n\n".join(feature_blocks)

    def extract_gpos_features_as_fea(self) -> str:
        """Extract existing GPOS features as FEA code."""
        if "GPOS" not in self.font:
            return ""

        gpos = self.font["GPOS"].table
        if not hasattr(gpos, "FeatureList") or not gpos.FeatureList:
            return ""

        feature_blocks = []

        # Process each feature
        for frec in gpos.FeatureList.FeatureRecord:
            feature_tag = frec.FeatureTag
            feature = frec.Feature

            # Get lookup indices for this feature
            lookup_indices = (
                feature.LookupListIndex if hasattr(feature, "LookupListIndex") else []
            )

            if not lookup_indices:
                continue

            # Extract positioning rules from lookups
            rules = []
            for lookup_idx in lookup_indices:
                if lookup_idx >= len(gpos.LookupList.Lookup):
                    continue

                lookup = gpos.LookupList.Lookup[lookup_idx]
                lookup_rules = self._extract_gpos_lookup_rules(lookup)
                rules.extend(lookup_rules)

            if rules:
                # Build feature block
                fea_lines = [f"feature {feature_tag} {{"]
                fea_lines.extend([f"  {rule}" for rule in rules])
                fea_lines.append(f"}} {feature_tag};")
                feature_blocks.append("\n".join(fea_lines))

        return "\n\n".join(feature_blocks)

    def extract_all_features_as_fea(self) -> str:
        """Extract all features (GSUB + GPOS) as FEA code."""
        gsub_fea = self.extract_gsub_features_as_fea()
        gpos_fea = self.extract_gpos_features_as_fea()

        parts = []
        if gsub_fea:
            parts.append("# GSUB Features\n" + gsub_fea)
        if gpos_fea:
            parts.append("# GPOS Features\n" + gpos_fea)

        return "\n\n".join(parts) if parts else ""

    def _extract_lookup_rules(self, lookup) -> List[str]:
        """Extract substitution rules from a lookup."""
        rules = []
        lookup_type = lookup.LookupType

        for subtable in lookup.SubTable:
            # Type 1: Single Substitution (one-to-one)
            if lookup_type == 1:
                rules.extend(self._extract_single_subst(subtable))
            # Type 4: Ligature Substitution (many-to-one)
            elif lookup_type == 4:
                rules.extend(self._extract_ligature_subst(subtable))
            # Other types: skip for now (could be extended)

        return rules

    def _extract_single_subst(self, subtable) -> List[str]:
        """Extract rules from SingleSubst table (Type 1)."""
        rules = []

        if hasattr(subtable, "mapping"):
            # Format 2: explicit mapping
            for input_glyph, output_glyph in subtable.mapping.items():
                rules.append(f"sub {input_glyph} by {output_glyph};")

        return rules

    def _extract_ligature_subst(self, subtable) -> List[str]:
        """Extract rules from LigatureSubst table (Type 4)."""
        rules = []

        if hasattr(subtable, "ligatures"):
            for first_glyph, lig_list in subtable.ligatures.items():
                for lig in lig_list:
                    # Build component list
                    components = [first_glyph] + lig.Component
                    lig_glyph = lig.LigGlyph
                    rules.append(f"sub {' '.join(components)} by {lig_glyph};")

        return rules

    def _extract_gpos_lookup_rules(self, lookup) -> List[str]:
        """Extract positioning rules from a GPOS lookup."""
        rules = []
        lookup_type = lookup.LookupType

        for subtable in lookup.SubTable:
            # Type 1: Single Adjustment (one-to-one positioning)
            if lookup_type == 1:
                rules.extend(self._extract_single_pos(subtable))
            # Type 2: Pair Adjustment (kerning)
            elif lookup_type == 2:
                rules.extend(self._extract_pair_pos(subtable))
            # Other types: skip for now (could be extended)

        return rules

    def _extract_single_pos(self, subtable) -> List[str]:
        """Extract rules from SinglePos table (Type 1)."""
        rules = []

        if hasattr(subtable, "Coverage") and hasattr(subtable, "Value"):
            # Format 1: same value for all glyphs
            coverage = subtable.Coverage
            if hasattr(coverage, "glyphs"):
                value = subtable.Value
                if value:
                    x_adv = getattr(value, "XAdvance", 0) or 0
                    y_adv = getattr(value, "YAdvance", 0) or 0
                    x_place = getattr(value, "XPlacement", 0) or 0
                    y_place = getattr(value, "YPlacement", 0) or 0

                    if x_adv != 0 or y_adv != 0 or x_place != 0 or y_place != 0:
                        for glyph in coverage.glyphs:
                            rules.append(
                                f"pos {glyph} <{x_place} {y_place} {x_adv} {y_adv}>;"
                            )

        return rules

    def _extract_pair_pos(self, subtable) -> List[str]:
        """Extract rules from PairPos table (Type 2 - kerning)."""
        rules = []

        if hasattr(subtable, "Coverage"):
            coverage = subtable.Coverage
            if hasattr(coverage, "glyphs"):
                # Format 2: class-based (simplified extraction)
                if hasattr(subtable, "ClassDef1") and hasattr(subtable, "ClassDef2"):
                    # Class-based kerning - extract as individual pairs if possible
                    # This is simplified - full extraction would require class analysis
                    pass
                # Format 1: pair adjustment
                elif hasattr(subtable, "PairSets"):
                    for first_glyph, pair_set in zip(
                        coverage.glyphs, subtable.PairSets
                    ):
                        if pair_set:
                            for pair_value in pair_set.PairValue:
                                second_glyph = pair_value.SecondGlyph
                                value = pair_value.Value1
                                if value:
                                    x_adv = getattr(value, "XAdvance", 0) or 0
                                    if x_adv != 0:
                                        rules.append(
                                            f"pos {first_glyph} {second_glyph} {x_adv};"
                                        )

        return rules


class ExistingSubstitutionExtractor:
    """Extract existing substitutions to avoid duplicates."""

    def __init__(self, font: TTFont):
        self.font = font

    def extract_all(self) -> Dict[str, Set]:
        """
        Extract all existing substitutions by type.

        Returns:
            {
                'ligatures': set of component tuples,
                'single': set of (input, output) tuples,
            }
        """
        result = {
            "ligatures": set(),
            "single": set(),
        }

        if "GSUB" not in self.font:
            return result

        gsub = self.font["GSUB"].table
        if not hasattr(gsub, "LookupList") or not gsub.LookupList:
            return result

        for lookup in gsub.LookupList.Lookup:
            if lookup.LookupType == 1:  # Single substitution
                for subtable in lookup.SubTable:
                    if hasattr(subtable, "mapping"):
                        for inp, out in subtable.mapping.items():
                            result["single"].add((inp, out))

            elif lookup.LookupType == 4:  # Ligature substitution
                for subtable in lookup.SubTable:
                    if hasattr(subtable, "ligatures"):
                        for first_glyph, lig_list in subtable.ligatures.items():
                            for lig in lig_list:
                                components = tuple([first_glyph] + lig.Component)
                                result["ligatures"].add(components)

        return result
