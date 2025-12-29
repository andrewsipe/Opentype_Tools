"""
Intelligent label generation for stylistic sets with confidence scoring.

Generates human-readable labels for stylistic sets based on glyph naming
patterns, Unicode categories, and semantic groups.
"""

import unicodedata
from typing import Dict, List, Tuple

from fontTools.ttLib import TTFont

from .detection import UnifiedGlyphDetector


class SSLabeler:
    """Generate intelligent labels for stylistic sets with confidence scoring."""

    def __init__(self, font: TTFont):
        self.font = font
        self.best_cmap = font.getBestCmap() or {}
        self.detector = UnifiedGlyphDetector(font)

    def suggest_label(
        self, ss_num: int, glyphs: List[Tuple[str, str]]
    ) -> Tuple[str, float]:
        """
        Suggest a label for a stylistic set with confidence score.

        Args:
            ss_num: Stylistic set number (1-20)
            glyphs: List of (base_glyph, alternate_glyph) tuples

        Returns:
            (suggested_label, confidence_score) tuple
            Confidence is 0.0-1.0, where 1.0 is highest confidence
        """
        if not glyphs:
            return f"Stylistic Set {ss_num:02d}", 0.0

        # Try each strategy in order of confidence
        strategies = [
            self._check_explicit_suffix,
            self._check_unicode_categories,
            self._check_semantic_groups,
            self._check_visual_patterns,
            self._fallback_description,
        ]

        best_label = None
        best_confidence = 0.0

        for strategy in strategies:
            label, confidence = strategy(ss_num, glyphs)
            if confidence > best_confidence:
                best_label = label
                best_confidence = confidence
                # If we have very high confidence, stop early
                if confidence >= 0.9:
                    break

        return best_label or f"Stylistic Set {ss_num:02d}", best_confidence

    def _check_explicit_suffix(
        self, ss_num: int, glyphs: List[Tuple[str, str]]
    ) -> Tuple[str, float]:
        """Check for explicit naming patterns (highest confidence)."""
        # Common patterns: .swash, .alt1, .alt2, .ornamental, etc.
        suffix_patterns = {
            "swash": "Swash",
            "swsh": "Swash",
            "alt": "Alternate",
            "alt1": "Alternate Style 1",
            "alt2": "Alternate Style 2",
            "ornamental": "Ornamental",
            "decorative": "Decorative",
            "flourish": "Flourish",
            "initial": "Initial",
            "terminal": "Terminal",
        }

        # Check alternate glyph names for common suffixes
        suffixes_found = {}
        for base, alternate in glyphs:
            for suffix, label_part in suffix_patterns.items():
                if alternate.endswith(f".{suffix}"):
                    suffixes_found[suffix] = suffixes_found.get(suffix, 0) + 1

        if suffixes_found:
            # Use most common suffix
            most_common = max(suffixes_found.items(), key=lambda x: x[1])
            suffix, count = most_common
            label_part = suffix_patterns[suffix]

            # Determine if it's for capitals, lowercase, or both
            base_types = self._analyze_base_types(glyphs)
            if base_types["uppercase"] > base_types["lowercase"]:
                label = f"{label_part} Capitals"
            elif base_types["lowercase"] > base_types["uppercase"]:
                label = f"{label_part} Lowercase"
            else:
                label = label_part

            # High confidence if most glyphs match pattern
            confidence = min(0.9, 0.7 + (count / len(glyphs)) * 0.2)
            return label, confidence

        return "", 0.0

    def _check_unicode_categories(
        self, ss_num: int, glyphs: List[Tuple[str, str]]
    ) -> Tuple[str, float]:
        """Check Unicode categories (high confidence)."""
        categories = {"Lu": 0, "Ll": 0, "Nd": 0, "Sc": 0, "So": 0}

        for base, alternate in glyphs:
            if base in self.best_cmap.values():
                # Find codepoint for base glyph
                for cp, gname in self.best_cmap.items():
                    if gname == base:
                        cat = unicodedata.category(chr(cp))
                        if cat in categories:
                            categories[cat] += 1
                        break

        total_categorized = sum(categories.values())
        if total_categorized == 0:
            return "", 0.0

        # Check if all are same category
        dominant_cat = max(categories.items(), key=lambda x: x[1])
        cat_name, count = dominant_cat

        if count == total_categorized:
            # All same category - high confidence
            label_map = {
                "Lu": "Stylistic Capitals",
                "Ll": "Stylistic Lowercase",
                "Nd": "Alternate Figures",
                "Sc": "Currency Variants",
                "So": "Symbol Variants",
            }
            label = label_map.get(cat_name, "Stylistic Alternates")
            confidence = 0.8
            return label, confidence
        elif count >= total_categorized * 0.8:
            # Mostly same category - medium confidence
            label_map = {
                "Lu": "Stylistic Capitals",
                "Ll": "Stylistic Lowercase",
                "Nd": "Alternate Figures",
                "Sc": "Currency Variants",
                "So": "Symbol Variants",
            }
            label = label_map.get(cat_name, "Stylistic Alternates")
            confidence = 0.7
            return label, confidence

        return "", 0.0

    def _check_semantic_groups(
        self, ss_num: int, glyphs: List[Tuple[str, str]]
    ) -> Tuple[str, float]:
        """Check semantic groups (medium confidence)."""
        # Group by common semantic patterns
        semantic_groups = {
            "currency": ["dollar", "cent", "pound", "yen", "euro"],
            "punctuation": ["period", "comma", "colon", "semicolon"],
            "brackets": ["parenleft", "parenright", "bracketleft", "bracketright"],
            "quotes": ["quotedbl", "quoteleft", "quoteright"],
        }

        matches = {}
        for group_name, patterns in semantic_groups.items():
            count = 0
            for base, alternate in glyphs:
                base_lower = base.lower()
                if any(pattern in base_lower for pattern in patterns):
                    count += 1
            if count > 0:
                matches[group_name] = count

        if matches:
            # Use most common match
            most_common = max(matches.items(), key=lambda x: x[1])
            group_name, count = most_common

            label_map = {
                "currency": "Currency Variants",
                "punctuation": "Alternate Punctuation",
                "brackets": "Alternate Brackets",
                "quotes": "Alternate Quotes",
            }

            label = label_map.get(group_name, "Stylistic Alternates")
            confidence = min(0.7, 0.5 + (count / len(glyphs)) * 0.2)
            return label, confidence

        return "", 0.0

    def _check_visual_patterns(
        self, ss_num: int, glyphs: List[Tuple[str, str]]
    ) -> Tuple[str, float]:
        """Check visual patterns like width/weight (low confidence)."""
        # This would require glyph metrics analysis
        # For now, return low confidence
        return "", 0.0

    def _fallback_description(
        self, ss_num: int, glyphs: List[Tuple[str, str]]
    ) -> Tuple[str, float]:
        """Fallback: describe by glyph list (lowest confidence)."""
        if len(glyphs) <= 3:
            base_names = [base for base, _ in glyphs]
            label = f"Alternates for {', '.join(base_names)}"
        else:
            base_names = [base for base, _ in glyphs[:3]]
            label = f"Alternates for {', '.join(base_names)} and {len(glyphs) - 3} more"

        return label, 0.3

    def _analyze_base_types(self, glyphs: List[Tuple[str, str]]) -> Dict[str, int]:
        """Analyze base glyph types."""
        types = {"uppercase": 0, "lowercase": 0, "other": 0}

        for base, alternate in glyphs:
            if base in self.best_cmap.values():
                # Find codepoint for base glyph
                for cp, gname in self.best_cmap.items():
                    if gname == base:
                        cat = unicodedata.category(chr(cp))
                        if cat == "Lu":
                            types["uppercase"] += 1
                        elif cat == "Ll":
                            types["lowercase"] += 1
                        else:
                            types["other"] += 1
                        break
            else:
                # Fallback: check if base name suggests case
                if base and base[0].isupper():
                    types["uppercase"] += 1
                elif base and base[0].islower():
                    types["lowercase"] += 1
                else:
                    types["other"] += 1

        return types
