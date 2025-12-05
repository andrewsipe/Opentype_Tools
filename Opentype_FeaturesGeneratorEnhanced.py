#!/usr/bin/env python3
"""
Unified OpenType Feature Tool (Enhanced Version)

Three modes of operation:

1. Feature Generation (default):
   Automatically detects and adds OpenType features to fonts based on glyph naming patterns.
   Analyzes glyph names, generates appropriate feature code, and adds them to fonts with
   proper name table labels for stylistic sets.

2. Audit/Repair Mode:
   Audits existing stylistic sets (ss01-ss20) for missing FeatureParams, invalid UINameIDs,
   missing labels, or conflicts. Can repair issues when combined with --apply.

3. Wrapper Subcommand:
   Adds minimal OpenType table scaffolding (cmap/GDEF/GPOS/GSUB) to fonts without format
   conversion. Can also enrich fonts by migrating legacy kern tables and inferring ligatures.

Supported Features (Generation Mode):
Original Features:
- Standard Ligatures (liga): f_f, f_i, f_f_i, fi, fl, etc.
- Stylistic Sets (ss01-ss20): .ss01, .ss02, etc. suffixes
- Small Caps (smcp): .sc, .smallcap suffixes
- Old-style Figures (onum): .oldstyle, .onum suffixes
- Lining Figures (lnum): .lining, .lnum suffixes
- Tabular Figures (tnum): .tabular, .tnum suffixes
- Proportional Figures (pnum): .proportional, .pnum suffixes
- Swashes (swsh): .swsh, .swash suffixes
- Discretionary Ligatures (dlig): Complex/decorative ligatures
- Contextual Alternates (calt): Context-sensitive variations

Phase 1 Enhanced Features:
- Fractions (frac): .numerator, .denominator, .numr, .dnom suffixes
- Superscripts (sups): .superior, .sups suffixes
- Subscripts (subs): .inferior, .subs suffixes
- Ordinals (ordn): .ordn suffixes (1st, 2nd, 3rd, etc.)
- Caps to Small Caps (c2sc): .c2sc suffixes
- Stylistic Alternates (salt): .alt, .alt01, .alt02 suffixes
- Slashed Zero (zero): .slash, .zero suffixes
- Case-Sensitive Forms (case): .case suffixes
- Titling Alternates (titl): .titling, .titl suffixes

Phase 2 Positioning Features (requires --enable-positioning):
- Capital Spacing (cpsp): Adds spacing between all-caps text
- Numerator (numr): Standalone numerator forms (.numr suffix)
- Denominator (dnom): Standalone denominator forms (.dnom suffix)
- Scientific Inferiors (sinf): Chemical formulas, mathematical notation (.sinf suffix)
- Historical Forms (hist): Long s, historical ligatures (.hist suffix)
- Kerning (kern): Audit and repair kerning pairs (requires --apply-kern-repair)

Usage Examples:
  # Analyze font (show detected features)
  ./Tools_OpentypeFeaturesGenerator.py font.otf

  # Apply all detected features
  ./Tools_OpentypeFeaturesGenerator.py font.otf --apply

  # Apply with custom stylistic set labels
  ./Tools_OpentypeFeaturesGenerator.py font.otf --apply -ss "14,Diamond Bullets" -ss "1,Swash Capitals"

  # Audit existing stylistic sets
  ./Tools_OpentypeFeaturesGenerator.py font.otf --audit

  # Repair existing stylistic sets
  ./Tools_OpentypeFeaturesGenerator.py font.otf --audit --apply -ss "14,Diamond Bullets" --add-missing-params

  # Add table scaffolding (wrapper subcommand)
  ./Tools_OpentypeFeaturesGenerator.py wrapper font.otf --enrich --drop-kern

  # Apply features with Phase 2 positioning enabled
  ./Tools_OpentypeFeaturesGenerator.py font.otf --apply --enable-positioning

  # Apply features with positioning and kern repair
  ./Tools_OpentypeFeaturesGenerator.py font.otf --apply --enable-positioning --apply-kern-repair

Exit code is non-zero if any error occurred.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import sys
import tempfile
import unicodedata
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Add project root to path for FontCore imports (works for root and subdirectory scripts)
_project_root = Path(__file__).parent
while (
    not (_project_root / "FontCore").exists() and _project_root.parent != _project_root
):
    _project_root = _project_root.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Core imports (after path setup)
import FontCore.core_console_styles as cs  # noqa: E402
from FontCore.core_file_collector import collect_font_files as core_collect_font_files  # noqa: E402
from fontTools.ttLib import TTFont, newTable  # noqa: E402
from fontTools.ttLib.tables import otTables  # noqa: E402
from fontTools.ttLib.tables.otTables import Coverage, ExtensionSubst, ExtensionPos  # noqa: E402
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable  # noqa: E402
from fontTools.agl import toUnicode  # noqa: E402

from opentype_features import (  # noqa: E402
    ExistingSubstitutionExtractor,
    FontValidator,
    WrapperStrategyEngine,
    WrapperExecutor,
    OperationResult,
)

# Suppress noisy fontTools warnings about coverage sorting
# Must be after fontTools imports
warnings.filterwarnings("ignore", message=".*Coverage.*not sorted.*")
logging.getLogger("fontTools").setLevel(logging.ERROR)

try:
    from fontTools.feaLib.builder import addOpenTypeFeaturesFromString

    HAVE_FEALIB = True
except Exception:
    HAVE_FEALIB = False

try:
    from fontFeatures.ttLib import unparse as fontfeatures_unparse
    from fontFeatures.optimizer import Optimizer

    HAVE_FONTFEATURES = True
except Exception:
    HAVE_FONTFEATURES = False
    fontfeatures_unparse = None
    Optimizer = None

SUPPORTED_EXTENSIONS = {".ttf", ".otf"}


# ============================================================================
# GLYPH PATTERN DETECTION
# ============================================================================


class GlyphPatternDetector:
    """Detects OpenType features based on glyph naming patterns."""

    def __init__(self, font: TTFont):
        self.font = font
        self.glyph_order = set(font.getGlyphOrder())
        self.best_cmap = font.getBestCmap() or {}

    def detect_all_features(self) -> Dict[str, List]:
        """Detect all supported feature patterns in the font."""
        features = {}

        # Ligatures (using existing logic)
        features["liga"] = self._detect_ligatures()

        # Stylistic sets
        features["stylistic_sets"] = self._detect_stylistic_sets()

        # Small caps
        features["smcp"] = self._detect_small_caps()

        # Figure variants
        features["onum"] = self._detect_figure_variant([".oldstyle", ".onum"])
        features["lnum"] = self._detect_figure_variant([".lining", ".lnum"])
        features["tnum"] = self._detect_figure_variant([".tabular", ".tnum"])
        features["pnum"] = self._detect_figure_variant([".proportional", ".pnum"])

        # Swashes
        features["swsh"] = self._detect_swash()

        # Discretionary ligatures
        features["dlig"] = self._detect_discretionary_ligatures()

        # Contextual alternates
        features["calt"] = self._detect_contextual_alternates()

        # Phase 1 enhanced features
        features["frac"] = self._detect_fractions()
        features["sups"] = self._detect_superscripts()
        features["subs"] = self._detect_subscripts()
        features["ordn"] = self._detect_ordinals()
        features["c2sc"] = self._detect_caps_to_small_caps()
        features["salt"] = self._detect_stylistic_alternates()
        features["zero"] = self._detect_slashed_zero()
        features["case"] = self._detect_case_sensitive()
        features["titl"] = self._detect_titling()

        # Phase 2 positioning features
        features["numr"] = self._detect_numr()
        features["dnom"] = self._detect_dnom()
        features["sinf"] = self._detect_sinf()
        features["hist"] = self._detect_hist()

        return features

    def _detect_ligatures(self) -> List[Tuple[List[str], str]]:
        """
        Detect standard ligatures from glyph names.
        Returns list of ([components...], ligatureGlyphName).
        """
        ligatures = []

        for glyph_name in self.glyph_order:
            components = self._parse_ligature_components(glyph_name)
            if components:
                ligatures.append((components, glyph_name))

        return ligatures

    def _parse_ligature_components(self, glyph_name: str) -> List[str]:
        """
        Parse ligature glyph name into component glyphs.
        Supports patterns like: f_f_i, uni0066_uni0069, fi, fl
        Now with proper validation to avoid false positives.
        """
        import unicodedata

        # Remove suffixes like .liga, .ss01, etc.
        base = glyph_name.split(".")[0]

        # Handle underscore-separated ligatures
        if "_" in base:
            parts = base.split("_")
        # Handle simple two-letter ligatures - BUT VALIDATE
        elif len(base) == 2 and all(ch.isalpha() for ch in base):
            # Check if this is actually a ligature or just a 2-letter glyph name
            # A real ligature should have both components exist as separate glyphs
            part1, part2 = base[0], base[1]

            # If base itself maps to a Unicode ligature character, it's a glyph, not a ligature
            try:
                uni = toUnicode(base)
                if uni and len(uni) == 1:
                    cp = ord(uni)
                    # Check if this is a precomposed Unicode ligature
                    name = unicodedata.name(chr(cp), "")
                    if "LIGATURE" in name:
                        # This is a precomposed ligature glyph, treat as single glyph
                        return []
            except Exception:
                pass

            # Check if both components exist
            if part1 not in self.glyph_order or part2 not in self.glyph_order:
                return []

            parts = [part1, part2]
        else:
            return []

        # Resolve uniXXXX tokens to glyph names
        resolved = []
        for part in parts:
            if part.startswith("uni") and len(part) >= 7:
                # Extract Unicode codepoint
                hex_part = part[3:7]
                try:
                    codepoint = int(hex_part, 16)
                    glyph = self.best_cmap.get(codepoint)
                    if not glyph:
                        return []  # Component not in cmap
                    resolved.append(glyph)
                except ValueError:
                    return []
            else:
                # Use part itself if it's a valid glyph
                if part in self.glyph_order:
                    resolved.append(part)
                else:
                    return []  # Component doesn't exist

        # Final validation: must have 2+ components
        if len(resolved) < 2:
            return []

        # Extra validation: check if all components have Unicode values
        # (helps filter out constructed names that aren't real ligatures)
        valid_components = 0
        for comp in resolved:
            if comp in self.best_cmap.values():
                valid_components += 1

        # At least half the components should have Unicode values
        if valid_components < len(resolved) / 2:
            return []

        return resolved

    def _detect_stylistic_sets(self) -> Dict[int, List[Tuple[str, str]]]:
        """
        Detect stylistic set alternates.
        Returns dict: {ss_number: [(base_glyph, alternate_glyph), ...]}
        """
        ss_pattern = re.compile(r"^(.+)\.ss(\d{2})$")
        stylistic_sets = defaultdict(list)

        for glyph_name in self.glyph_order:
            match = ss_pattern.match(glyph_name)
            if match:
                base_name = match.group(1)
                ss_num = int(match.group(2))

                # Only include ss01-ss99 (we'll handle limiting to 20 later)
                if 1 <= ss_num <= 99:
                    # Check if base glyph exists
                    if base_name in self.glyph_order:
                        stylistic_sets[ss_num].append((base_name, glyph_name))

        return dict(stylistic_sets)

    def _detect_small_caps(self) -> List[Tuple[str, str]]:
        """
        Detect small caps glyphs.
        Returns list of (base_glyph, sc_glyph) tuples.
        """
        sc_pattern = re.compile(r"^(.+)\.(sc|smallcap)$")
        small_caps = []

        for glyph_name in self.glyph_order:
            match = sc_pattern.match(glyph_name)
            if match:
                base_name = match.group(1)
                if base_name in self.glyph_order:
                    small_caps.append((base_name, glyph_name))

        return small_caps

    def _detect_figure_variant(self, suffixes: List[str]) -> List[Tuple[str, str]]:
        """
        Detect figure variants with given suffixes.
        Returns list of (base_glyph, variant_glyph) tuples.
        """
        variants = []

        for glyph_name in self.glyph_order:
            for suffix in suffixes:
                if glyph_name.endswith(suffix):
                    base_name = glyph_name[: -len(suffix)]
                    if base_name in self.glyph_order:
                        variants.append((base_name, glyph_name))
                        break

        return variants

    def _detect_swash(self) -> List[Tuple[str, str]]:
        """
        Detect swash alternates.
        Returns list of (base_glyph, swash_glyph) tuples.
        """
        swash_pattern = re.compile(r"^(.+)\.(swsh|swash)$")
        swashes = []

        for glyph_name in self.glyph_order:
            match = swash_pattern.match(glyph_name)
            if match:
                base_name = match.group(1)
                if base_name in self.glyph_order:
                    swashes.append((base_name, glyph_name))

        return swashes

    def _detect_discretionary_ligatures(self) -> List[Tuple[List[str], str]]:
        """
        Detect discretionary ligatures (complex/decorative).
        Currently looks for .dlig suffix.
        """
        dlig_pattern = re.compile(r"^(.+)\.dlig$")
        dligatures = []

        for glyph_name in self.glyph_order:
            match = dlig_pattern.match(glyph_name)
            if match:
                base_name = match.group(1)
                # Try to parse as ligature
                components = self._parse_ligature_components(base_name)
                if components:
                    dligatures.append((components, glyph_name))

        return dligatures

    def _detect_contextual_alternates(self) -> List[Tuple[str, str]]:
        """
        Detect contextual alternates.
        Looks for patterns like: .calt, .alt, .calt01, .alt01, etc.
        """
        calt_pattern = re.compile(r"^(.+)\.(calt|alt)(\d+)?$")
        contextual_alternates = []

        for glyph_name in self.glyph_order:
            match = calt_pattern.match(glyph_name)
            if match:
                base_name = match.group(1)
                if base_name in self.glyph_order:
                    contextual_alternates.append((base_name, glyph_name))

        return contextual_alternates

    def _detect_fractions(self) -> Dict[str, List[Tuple[str, str]]]:
        """Detect fraction numerator and denominator glyphs."""
        from opentype_features.opentype_features_config import CONFIG

        patterns = CONFIG.PHASE1_FEATURE_PATTERNS.get("frac", [])
        numerators = []
        denominators = []

        for glyph_name in self.glyph_order:
            for pattern in patterns:
                if glyph_name.endswith(pattern):
                    base_name = glyph_name[: -len(pattern)]
                    if base_name in self.glyph_order:
                        if "numerator" in pattern or "numr" in pattern:
                            numerators.append((base_name, glyph_name))
                        elif "denominator" in pattern or "dnom" in pattern:
                            denominators.append((base_name, glyph_name))
                    break

        return {"numerators": numerators, "denominators": denominators}

    def _detect_superscripts(self) -> List[Tuple[str, str]]:
        """Detect superscript variants."""
        from opentype_features.opentype_features_config import CONFIG

        patterns = CONFIG.PHASE1_FEATURE_PATTERNS.get("sups", [])
        superscripts = []

        for glyph_name in self.glyph_order:
            for pattern in patterns:
                if glyph_name.endswith(pattern):
                    base_name = glyph_name[: -len(pattern)]
                    if base_name in self.glyph_order:
                        superscripts.append((base_name, glyph_name))
                    break

        return superscripts

    def _detect_subscripts(self) -> List[Tuple[str, str]]:
        """Detect subscript variants."""
        from opentype_features.opentype_features_config import CONFIG

        patterns = CONFIG.PHASE1_FEATURE_PATTERNS.get("subs", [])
        subscripts = []

        for glyph_name in self.glyph_order:
            for pattern in patterns:
                if glyph_name.endswith(pattern):
                    base_name = glyph_name[: -len(pattern)]
                    if base_name in self.glyph_order:
                        subscripts.append((base_name, glyph_name))
                    break

        return subscripts

    def _detect_ordinals(self) -> List[Tuple[str, str]]:
        """Detect ordinal variants."""
        from opentype_features.opentype_features_config import CONFIG

        patterns = CONFIG.PHASE1_FEATURE_PATTERNS.get("ordn", [])
        ordinals = []

        for glyph_name in self.glyph_order:
            for pattern in patterns:
                if glyph_name.endswith(pattern):
                    base_name = glyph_name[: -len(pattern)]
                    if base_name in self.glyph_order:
                        ordinals.append((base_name, glyph_name))
                    break

        return ordinals

    def _detect_caps_to_small_caps(self) -> List[Tuple[str, str]]:
        """Detect caps-to-small-caps variants."""
        from opentype_features.opentype_features_config import CONFIG

        patterns = CONFIG.PHASE1_FEATURE_PATTERNS.get("c2sc", [])
        c2sc_variants = []

        for glyph_name in self.glyph_order:
            for pattern in patterns:
                if glyph_name.endswith(pattern):
                    base_name = glyph_name[: -len(pattern)]
                    if base_name in self.glyph_order and base_name.isupper():
                        c2sc_variants.append((base_name, glyph_name))
                    break

        return c2sc_variants

    def _detect_stylistic_alternates(self) -> List[Tuple[str, str]]:
        """Detect stylistic alternates (salt)."""
        from opentype_features.opentype_features_config import CONFIG

        patterns = CONFIG.PHASE1_FEATURE_PATTERNS.get("salt", [])
        salt_alternates = []
        # calt pattern matches .calt and .alt (with optional number)
        calt_pattern = re.compile(r"^(.+)\.(calt|alt)(\d+)?$")

        for glyph_name in self.glyph_order:
            for pattern in patterns:
                if glyph_name.endswith(pattern):
                    base_name = glyph_name[: -len(pattern)]
                    if base_name in self.glyph_order:
                        # Check if this matches calt pattern
                        calt_match = calt_pattern.match(glyph_name)
                        if calt_match:
                            # If it's plain .alt (no number), calt takes precedence, skip
                            # If it's .alt01, .alt02, etc., include in salt (numbered = salt)
                            alt_num = calt_match.group(3)
                            if alt_num is None and pattern == ".alt":
                                # Plain .alt goes to calt, skip for salt
                                break
                            elif alt_num is not None:
                                # Numbered alternates (.alt01, .alt02) go to salt
                                salt_alternates.append((base_name, glyph_name))
                                break
                        else:
                            # Pattern doesn't match calt, include in salt
                            salt_alternates.append((base_name, glyph_name))
                            break

        return salt_alternates

    def _detect_slashed_zero(self) -> List[Tuple[str, str]]:
        """Detect slashed zero variants."""
        from opentype_features.opentype_features_config import CONFIG

        patterns = CONFIG.PHASE1_FEATURE_PATTERNS.get("zero", [])
        slashed_zeros = []

        for glyph_name in self.glyph_order:
            for pattern in patterns:
                if glyph_name.endswith(pattern):
                    base_name = glyph_name[: -len(pattern)]
                    if base_name == "zero" or base_name == "0":
                        slashed_zeros.append((base_name, glyph_name))
                    break

        return slashed_zeros

    def _detect_case_sensitive(self) -> List[Tuple[str, str]]:
        """Detect case-sensitive form variants."""
        from opentype_features.opentype_features_config import CONFIG

        patterns = CONFIG.PHASE1_FEATURE_PATTERNS.get("case", [])
        case_variants = []

        for glyph_name in self.glyph_order:
            for pattern in patterns:
                if glyph_name.endswith(pattern):
                    base_name = glyph_name[: -len(pattern)]
                    if base_name in self.glyph_order:
                        case_variants.append((base_name, glyph_name))
                    break

        return case_variants

    def _detect_titling(self) -> List[Tuple[str, str]]:
        """Detect titling alternate variants."""
        from opentype_features.opentype_features_config import CONFIG

        patterns = CONFIG.PHASE1_FEATURE_PATTERNS.get("titl", [])
        titling_variants = []

        for glyph_name in self.glyph_order:
            for pattern in patterns:
                if glyph_name.endswith(pattern):
                    base_name = glyph_name[: -len(pattern)]
                    if base_name in self.glyph_order:
                        titling_variants.append((base_name, glyph_name))
                    break

        return titling_variants

    def _detect_numr(self) -> List[Tuple[str, str]]:
        """Detect standalone numerator glyphs."""
        from opentype_features.opentype_features_config import CONFIG

        patterns = CONFIG.PHASE2_FEATURE_PATTERNS.get("numr", [])
        numr_variants = []

        for glyph_name in self.glyph_order:
            for pattern in patterns:
                if glyph_name.endswith(pattern):
                    base_name = glyph_name[: -len(pattern)]
                    if base_name in self.glyph_order:
                        numr_variants.append((base_name, glyph_name))
                    break

        return numr_variants

    def _detect_dnom(self) -> List[Tuple[str, str]]:
        """Detect standalone denominator glyphs."""
        from opentype_features.opentype_features_config import CONFIG

        patterns = CONFIG.PHASE2_FEATURE_PATTERNS.get("dnom", [])
        dnom_variants = []

        for glyph_name in self.glyph_order:
            for pattern in patterns:
                if glyph_name.endswith(pattern):
                    base_name = glyph_name[: -len(pattern)]
                    if base_name in self.glyph_order:
                        dnom_variants.append((base_name, glyph_name))
                    break

        return dnom_variants

    def _detect_sinf(self) -> List[Tuple[str, str]]:
        """Detect scientific inferior glyphs."""
        from opentype_features.opentype_features_config import CONFIG

        patterns = CONFIG.PHASE2_FEATURE_PATTERNS.get("sinf", [])
        sinf_variants = []

        for glyph_name in self.glyph_order:
            for pattern in patterns:
                if glyph_name.endswith(pattern):
                    base_name = glyph_name[: -len(pattern)]
                    if base_name in self.glyph_order:
                        sinf_variants.append((base_name, glyph_name))
                    break

        return sinf_variants

    def _detect_hist(self) -> List[Tuple[str, str]]:
        """Detect historical form glyphs."""
        from opentype_features.opentype_features_config import CONFIG

        patterns = CONFIG.PHASE2_FEATURE_PATTERNS.get("hist", [])
        hist_variants = []

        for glyph_name in self.glyph_order:
            for pattern in patterns:
                if glyph_name.endswith(pattern):
                    base_name = glyph_name[: -len(pattern)]
                    if base_name in self.glyph_order:
                        hist_variants.append((base_name, glyph_name))
                    break

        return hist_variants


# ============================================================================
# COVERAGE TABLE SORTING
# ============================================================================


def find_all_coverage_tables(font):
    """
    Recursively find all Coverage objects in GSUB/GPOS tables.
    Returns list of (path, coverage_object) tuples.
    """
    coverages = []

    def recurse_coverage(obj, path="", visited=None):
        if visited is None:
            visited = set()

        obj_id = id(obj)
        if obj_id in visited:
            return
        visited.add(obj_id)

        if isinstance(obj, Coverage):
            coverages.append((path, obj))
            return

        if isinstance(obj, (ExtensionSubst, ExtensionPos)):
            if hasattr(obj, "ExtSubTable") and obj.ExtSubTable is not None:
                recurse_coverage(obj.ExtSubTable, path + ".ExtSubTable", visited)
            return

        if hasattr(obj, "__dict__"):
            for attr, value in obj.__dict__.items():
                if value is None:
                    continue
                new_path = f"{path}.{attr}" if path else attr

                if isinstance(value, list):
                    for i, item in enumerate(value):
                        recurse_coverage(item, f"{new_path}[{i}]", visited)
                else:
                    recurse_coverage(value, new_path, visited)

    for table_name in ["GSUB", "GPOS"]:
        if table_name not in font:
            continue

        table = font[table_name].table
        if hasattr(table, "LookupList") and table.LookupList:
            for lookup_idx, lookup in enumerate(table.LookupList.Lookup):
                if not hasattr(lookup, "SubTable") or not lookup.SubTable:
                    continue

                for subtable_idx, subtable in enumerate(lookup.SubTable):
                    base_path = (
                        f"{table_name}.Lookup[{lookup_idx}].SubTable[{subtable_idx}]"
                    )
                    recurse_coverage(subtable, base_path)

    return coverages


def extract_glyph_order_from_ttx(ttx_content):
    """
    Extract the GlyphOrder from TTX XML content.
    Returns a dict mapping glyph names to their IDs.
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(ttx_content)
    except ET.ParseError as e:
        raise ValueError(f"Invalid TTX XML: {e}")

    glyph_order = root.find("GlyphOrder")
    if glyph_order is None:
        raise ValueError("No GlyphOrder table found in TTX content")

    glyph_to_id = {}
    for glyph_id_elem in glyph_order.findall("GlyphID"):
        glyph_name = glyph_id_elem.get("name")
        glyph_id = int(glyph_id_elem.get("id"))
        if glyph_name:
            glyph_to_id[glyph_name] = glyph_id

    return glyph_to_id


def sort_coverage_tables_in_ttx_content(ttx_content, glyph_to_id, verbose=False):
    """
    Sort Coverage tables in TTX XML content by glyph ID.
    Returns (total_coverage, sorted_count, sorted_content)
    """
    import re

    total_coverage = 0
    sorted_coverage = 0

    # Pattern to match Coverage blocks with their Glyph entries
    def process_coverage_block(match):
        nonlocal total_coverage, sorted_coverage

        total_coverage += 1
        full_block = match.group(0)
        indent = match.group(1)
        coverage_attrs = match.group(2)
        inner_content = match.group(3)

        # Find all Glyph value lines
        glyph_pattern = re.compile(r'(\s*)<Glyph value="([^"]+)"/>')
        glyph_matches = list(glyph_pattern.finditer(inner_content))

        if len(glyph_matches) <= 1:
            return full_block

        # Extract glyph values
        glyph_values = [m.group(2) for m in glyph_matches]

        # Sort by glyph ID (position in GlyphOrder)
        # Glyphs not in GlyphOrder get a high number to sort last
        sorted_values = sorted(glyph_values, key=lambda g: glyph_to_id.get(g, 999999))

        # Check if sorting is needed
        if glyph_values == sorted_values:
            return full_block

        sorted_coverage += 1

        if verbose:
            # Show what changed
            unsorted_ids = [glyph_to_id.get(g, -1) for g in glyph_values[:5]]
            sorted_ids = [glyph_to_id.get(g, -1) for g in sorted_values[:5]]
            cs.StatusIndicator("info").add_message(
                f"Sorted Coverage (was IDs {unsorted_ids}, now {sorted_ids})"
            ).emit()

        # Rebuild the Coverage block with sorted glyphs
        # Detect the indentation of the first Glyph element
        first_glyph_indent = glyph_matches[0].group(1) if glyph_matches else "        "

        # Build sorted glyph lines
        sorted_glyph_lines = [
            f'{first_glyph_indent}<Glyph value="{value}"/>' for value in sorted_values
        ]

        # Reconstruct the Coverage block
        result = f"{indent}<Coverage{coverage_attrs}>\n"
        result += "\n".join(sorted_glyph_lines)
        result += f"\n{indent}</Coverage>"

        return result

    # Pattern to match Coverage blocks
    coverage_pattern = re.compile(
        r"(\s*)<Coverage([^>]*)>\s*\n((?:\s*<Glyph[^>]+/>\s*\n)+)\s*\1</Coverage>",
        re.MULTILINE,
    )

    # Replace all Coverage blocks with sorted versions
    sorted_content = coverage_pattern.sub(process_coverage_block, ttx_content)

    return total_coverage, sorted_coverage, sorted_content


def sort_coverage_tables_in_font(font, verbose=False):
    """
    Sort all Coverage tables in a font by glyph ID using TTX conversion.
    This ensures sorting matches the exact behavior of Tools_TTX_GSUB_GPOS_CoverageTableSorter.py
    by converting to TTX, sorting by GlyphOrder IDs, then converting back.

    The font object is modified in place by reloading from the sorted TTX.

    Args:
        font: TTFont object (will be reloaded from sorted TTX if sorting occurs)
        verbose: Whether to show verbose output

    Returns:
        (total_coverage, sorted_count) tuple
    """
    import tempfile
    import os
    from io import StringIO

    try:
        # Convert font to TTX XML string using fontTools
        ttx_buffer = StringIO()
        font.saveXML(ttx_buffer)
        ttx_content = ttx_buffer.getvalue()

        # Extract GlyphOrder to get glyph IDs (matching TTX sorter logic exactly)
        glyph_to_id = extract_glyph_order_from_ttx(ttx_content)

        if verbose:
            cs.StatusIndicator("info").add_message(
                f"Extracted {len(glyph_to_id)} glyphs from GlyphOrder"
            ).emit()

        # Sort Coverage tables in TTX content using exact TTX sorter logic
        total, sorted_count, sorted_ttx_content = sort_coverage_tables_in_ttx_content(
            ttx_content, glyph_to_id, verbose
        )

        # If sorting occurred, reload font from sorted TTX
        if sorted_count > 0:
            # Determine output extension based on font type (before closing font)
            font_ext = ".otf"  # Default to OTF
            if hasattr(font, "sfntVersion"):
                # Check if it's TTF or OTF
                # TTF: "\x00\x01\x00\x00", OTF: "OTTO"
                if font.sfntVersion == "\x00\x01\x00\x00":
                    font_ext = ".ttf"

            # Use temporary file for TTX
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".ttx", delete=False, encoding="utf-8"
            ) as tmp_ttx:
                tmp_ttx.write(sorted_ttx_content)
                tmp_ttx_path = tmp_ttx.name

            # Create temp binary file path (same directory, different extension)
            tmp_bin_path = tmp_ttx_path.rsplit(".", 1)[0] + font_ext

            try:
                # Convert sorted TTX back to binary using ttx command-line tool
                import subprocess

                # Use ttx to compile TTX back to binary
                # ttx -f -o output.otf input.ttx
                # -f forces overwrite, -o specifies output file
                result = subprocess.run(
                    ["ttx", "-f", "-o", tmp_bin_path, tmp_ttx_path],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                if result.returncode != 0:
                    error_msg = result.stderr or result.stdout or "Unknown error"
                    raise ValueError(f"ttx compilation failed: {error_msg}")

                # Verify the output file was created and has content
                if not os.path.exists(tmp_bin_path):
                    raise ValueError(
                        f"ttx compilation succeeded but output file not found: {tmp_bin_path}"
                    )

                if os.path.getsize(tmp_bin_path) == 0:
                    raise ValueError(
                        f"ttx compilation created empty file: {tmp_bin_path}"
                    )

                # Reload font from sorted binary file
                # Load new font first (before closing old one to preserve any file paths)
                try:
                    new_font = TTFont(tmp_bin_path, lazy=False)
                except Exception as load_error:
                    raise ValueError(
                        f"Failed to load compiled font from {tmp_bin_path}: {load_error}. "
                        f"TTX file: {tmp_ttx_path}, ttx output: {result.stdout}, errors: {result.stderr}"
                    )

                # Update the original font object by replacing its internal state
                # Get list of existing table tags before closing (for cleanup)
                old_tags = list(font.keys()) if hasattr(font, "keys") else []

                # Copy all tables from new font to old font BEFORE closing
                # This way the font object is still valid
                for tag in new_font.keys():
                    font[tag] = new_font[tag]

                # Remove old tables that won't be replaced
                for tag in old_tags:
                    if tag not in new_font:
                        try:
                            del font[tag]
                        except Exception:
                            pass

                # Copy font-level attributes
                if hasattr(new_font, "sfntVersion"):
                    font.sfntVersion = new_font.sfntVersion
                if hasattr(new_font, "flavor"):
                    font.flavor = new_font.flavor
                if hasattr(new_font, "lazy"):
                    font.lazy = new_font.lazy

                # Close both fonts
                new_font.close()
                # Note: We don't close the original font here as it's still in use
                # The caller will close it when done

                # Clean up temp files
                os.unlink(tmp_ttx_path)
                os.unlink(tmp_bin_path)

            except FileNotFoundError:
                # ttx command not found - fall back to binary sorting
                if verbose:
                    cs.StatusIndicator("warning").add_message(
                        "ttx command not found, falling back to binary sorting"
                    ).emit()
                os.unlink(tmp_ttx_path)
                # Fall through to binary sorting below
                raise ValueError("ttx command not available")
            except Exception as e:
                # Clean up temp files on error
                try:
                    os.unlink(tmp_ttx_path)
                    if "tmp_bin_path" in locals() and os.path.exists(tmp_bin_path):
                        os.unlink(tmp_bin_path)
                except Exception:
                    pass
                raise ValueError(f"Failed to reload font from sorted TTX: {e}")

        return total, sorted_count

    except Exception as e:
        if verbose:
            cs.StatusIndicator("warning").add_message(
                f"TTX-based sorting failed: {e}"
            ).with_explanation("Coverage tables may not be sorted correctly").emit()

        # Return zero counts on error
        return 0, 0


# ============================================================================
# FEATURE EXTRACTION
# ============================================================================


class FeatureExtractor:
    """Extracts existing OpenType features from a font as FEA code."""

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


# ============================================================================
# FEATURE CODE GENERATION
# ============================================================================


class FeatureCodeGenerator:
    """Generates OpenType feature code from detected patterns."""

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


# ============================================================================
# STYLISTIC SET MANAGER
# ============================================================================


class StylisticSetManager:
    """Manages stylistic sets including name table labels and combining logic."""

    def __init__(self, font: TTFont, max_sets: int = 20):
        self.font = font
        self.max_sets = max_sets
        self.name_table = font.get("name")

    def generate_label_from_glyphs(
        self, ss_num: int, substitutions: List[Tuple[str, str]]
    ) -> str:
        """Generate a descriptive label for a stylistic set based on its glyphs."""
        if not substitutions:
            return f"Stylistic Set {ss_num:02d}"

        # Extract base glyph names
        base_glyphs = [base for base, alt in substitutions]

        # Analyze the types of glyphs
        uppercase_count = sum(
            1 for g in base_glyphs if g.isupper() or g in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        )
        lowercase_count = sum(
            1 for g in base_glyphs if g.islower() or g in "abcdefghijklmnopqrstuvwxyz"
        )
        digit_count = sum(
            1 for g in base_glyphs if g.isdigit() or any(d in g for d in "0123456789")
        )

        # Check for specific patterns in alternate names
        alt_glyphs = [alt for base, alt in substitutions]
        has_swash = any(
            "swash" in alt.lower() or "swsh" in alt.lower() for alt in alt_glyphs
        )

        # Generate label based on glyph types
        if digit_count >= len(base_glyphs) * 0.8:  # Mostly numbers
            return "Alternate Figures"
        elif uppercase_count >= len(base_glyphs) * 0.8:  # Mostly uppercase
            if has_swash:
                return "Swash Capitals"
            return "Stylistic Capitals"
        elif lowercase_count >= len(base_glyphs) * 0.8:  # Mostly lowercase
            if has_swash:
                return "Swash Lowercase"
            return "Stylistic Lowercase"
        elif has_swash:
            return "Swash Alternates"

        # If mixed or unclear, list some glyphs
        if len(base_glyphs) <= 5:
            glyph_list = ", ".join(sorted(base_glyphs))
            return f"Alternates for {glyph_list}"
        else:
            # Show first few
            sample = ", ".join(sorted(base_glyphs)[:4])
            return f"Alternates ({sample}...)"

    def allocate_name_id(self, start: int = 256) -> int:
        """Find an unused nameID starting from the given value."""
        if not self.name_table:
            return start

        used_ids = {rec.nameID for rec in self.name_table.names}
        name_id = start
        while name_id in used_ids:
            name_id += 1
        return name_id

    def add_name_record(self, name_id: int, label: str) -> None:
        """Add a Windows/English name table record."""
        if not self.name_table:
            return

        # Add Windows Unicode record (platformID=3, platEncID=1, langID=0x0409)
        self.name_table.setName(label, name_id, 3, 1, 0x0409)

    def combine_stylistic_sets(
        self, detected_sets: Dict[int, List[Tuple[str, str]]]
    ) -> Dict[int, List[Tuple[str, str]]]:
        """
        Combine stylistic sets when more than max_sets are detected.
        Prioritizes sets by glyph count, then combines related sets.
        """
        if len(detected_sets) <= self.max_sets:
            return detected_sets

        # Sort sets by glyph count (descending), then by set number
        sorted_sets = sorted(detected_sets.items(), key=lambda x: (-len(x[1]), x[0]))

        # Take top sets up to max_sets
        combined = {}
        remaining = []

        for ss_num, substitutions in sorted_sets[: self.max_sets]:
            combined[ss_num] = substitutions

        # Collect remaining sets for combination
        for ss_num, substitutions in sorted_sets[self.max_sets :]:
            remaining.append((ss_num, substitutions))

        # Try to combine remaining sets into existing ones
        # Group by similar glyph bases (e.g., all A alternates together)
        base_glyph_map = defaultdict(list)
        for ss_num, substitutions in remaining:
            for base, alt in substitutions:
                base_glyph_map[base].append((ss_num, alt))

        # Distribute remaining alternates into existing sets
        for base, alternates in base_glyph_map.items():
            # Find a set that already has this base or a similar one
            target_ss = None
            for ss_num in sorted(combined.keys()):
                # Check if this set already has alternates for this base
                existing_bases = {sub[0] for sub in combined[ss_num]}
                if base in existing_bases or len(combined[ss_num]) < 50:
                    target_ss = ss_num
                    break

            if target_ss is None:
                # Use the smallest set
                target_ss = min(combined.keys(), key=lambda k: len(combined[k]))

            # Add alternates to target set
            for ss_num, alt in alternates:
                if (base, alt) not in combined[target_ss]:
                    combined[target_ss].append((base, alt))

        return combined

    def process_stylistic_sets(
        self,
        detected_sets: Dict[int, List[Tuple[str, str]]],
        custom_labels: Optional[Dict[int, str]] = None,
    ) -> Dict[int, Tuple[List[Tuple[str, str]], int, str]]:
        """
        Process detected stylistic sets and prepare them for feature generation.

        Returns: {ss_num: (substitutions, name_id, label)}
        """
        processed = {}

        # Combine sets if needed
        if len(detected_sets) > self.max_sets:
            cs.StatusIndicator("warning").add_message(
                f"Found {len(detected_sets)} stylistic sets, combining into {self.max_sets} sets"
            ).emit()
            detected_sets = self.combine_stylistic_sets(detected_sets)

        # Sort by set number
        sorted_nums = sorted(detected_sets.keys())

        for ss_num in sorted_nums:
            substitutions = detected_sets[ss_num]
            name_id = self.allocate_name_id()

            # Use custom label if provided, otherwise auto-generate from glyphs
            if custom_labels and ss_num in custom_labels:
                label = custom_labels[ss_num]
            else:
                # Auto-generate descriptive label
                label = self.generate_label_from_glyphs(ss_num, substitutions)

            processed[ss_num] = (substitutions, name_id, label)

        return processed


# ============================================================================
# AUDIT/REPAIR FUNCTIONALITY FOR EXISTING STYLISTIC SETS
# ============================================================================


def has_windows_name_id(name_table, name_id):
    """Check if a Windows nameID exists in the name table."""
    for rec in name_table.names:
        if rec.platformID == 3 and rec.nameID == name_id:
            return True
    return False


def get_name_strings_by_id(name_table, name_id):
    """Get all name strings for a given nameID."""
    vals = set()
    for rec in name_table.names:
        if rec.platformID == 3 and rec.nameID == name_id:
            try:
                vals.add(rec.toUnicode())
            except Exception:
                try:
                    vals.add(rec.string.decode("utf-16-be", errors="ignore"))
                except Exception:
                    try:
                        vals.add(rec.string.decode("latin-1", errors="ignore"))
                    except Exception:
                        pass
    return vals


def collect_used_name_ids(font):
    """Collect all nameIDs used by GSUB/GPOS/STAT/fvar tables."""
    used = set()
    # All FeatureParams UINameIDs (GSUB/GPOS, not only ssXX)
    for tableTag in ("GSUB", "GPOS"):
        if tableTag in font:
            flist = getattr(font[tableTag].table, "FeatureList", None)
            if flist:
                for frec in flist.FeatureRecord:
                    feat = frec.Feature
                    params = getattr(feat, "FeatureParams", None)
                    nid = getattr(params, "UINameID", None) if params else None
                    if isinstance(nid, int) and nid >= 0:
                        used.add(nid)
    # STAT Axis and AxisValue names
    if "STAT" in font:
        st = font["STAT"].table
        dar = getattr(st, "DesignAxisRecord", None)
        if dar and getattr(dar, "Axis", None):
            for axis in dar.Axis:
                nid = getattr(axis, "AxisNameID", None)
                if isinstance(nid, int):
                    used.add(nid)
        ava = getattr(st, "AxisValueArray", None)
        if ava and getattr(ava, "AxisValue", None):
            for av in ava.AxisValue:
                if hasattr(av, "ValueNameID"):
                    used.add(av.ValueNameID)
                elif hasattr(av, "AxisValueRecord"):
                    for avr in av.AxisValueRecord:
                        used.add(avr.ValueNameID)
    # fvar instance names
    if "fvar" in font:
        fvar = font["fvar"]
        for inst in getattr(fvar, "instances", []):
            nid = getattr(inst, "subfamilyNameID", None)
            if isinstance(nid, int):
                used.add(nid)
            psid = getattr(inst, "postscriptNameID", None)
            if isinstance(psid, int) and psid not in (-1, 0xFFFF):
                used.add(psid)
    return used


def collect_name_id_usage(font):
    """Collect detailed usage information for each nameID."""
    usage = {}

    def add_use(nid, why):
        if nid is None or not isinstance(nid, int) or nid < 0:
            return
        usage.setdefault(nid, []).append(why)

    # GSUB/GPOS FeatureParams UINameID
    for tableTag in ("GSUB", "GPOS"):
        if tableTag in font:
            flist = getattr(font[tableTag].table, "FeatureList", None)
            if flist:
                for frec in flist.FeatureRecord:
                    feat = frec.Feature
                    params = getattr(feat, "FeatureParams", None)
                    nid = getattr(params, "UINameID", None) if params else None
                    if isinstance(nid, int):
                        tag = getattr(frec, "FeatureTag", "????")
                        add_use(nid, f"{tableTag}.{tag} FeatureParams.UINameID")
    # STAT
    if "STAT" in font:
        st = font["STAT"].table
        dar = getattr(st, "DesignAxisRecord", None)
        if dar and getattr(dar, "Axis", None):
            for axis in dar.Axis:
                add_use(
                    getattr(axis, "AxisNameID", None),
                    f"STAT.DesignAxis.AxisNameID tag={getattr(axis, 'AxisTag', '----')}",
                )
        ava = getattr(st, "AxisValueArray", None)
        if ava and getattr(ava, "AxisValue", None):
            for av in ava.AxisValue:
                if hasattr(av, "ValueNameID"):
                    add_use(av.ValueNameID, "STAT.AxisValue.ValueNameID")
                elif hasattr(av, "AxisValueRecord"):
                    for avr in av.AxisValueRecord:
                        add_use(
                            getattr(avr, "ValueNameID", None),
                            "STAT.AxisValueRecord.ValueNameID",
                        )
    # fvar
    if "fvar" in font:
        fvar = font["fvar"]
        for idx, inst in enumerate(getattr(fvar, "instances", []) or []):
            add_use(
                getattr(inst, "subfamilyNameID", None),
                f"fvar.instances[{idx}].subfamilyNameID",
            )
            psid = getattr(inst, "postscriptNameID", None)
            if isinstance(psid, int) and psid not in (-1, 0xFFFF):
                add_use(psid, f"fvar.instances[{idx}].postscriptNameID")
    return usage


def collect_ss_feature_records_by_number(gsub_table):
    """Collect stylistic set feature records grouped by number."""
    groups = {}
    flist = gsub_table.table.FeatureList
    if not flist:
        return groups
    for frec in flist.FeatureRecord:
        tag = frec.FeatureTag
        if tag.startswith("ss") and len(tag) == 4 and tag[2:].isdigit():
            num = int(tag[2:])
            if 1 <= num <= 20:
                groups.setdefault(num, []).append(frec)
    return groups


def collect_referenced_ui_name_ids_by_ss(groups):
    """Map ss_num -> set of referenced UINameID (>=256) found in FeatureParams."""
    ref = {}
    for ss_num, records in groups.items():
        ids = set()
        for frec in records:
            params = getattr(frec.Feature, "FeatureParams", None)
            if params is not None:
                nid = getattr(params, "UINameID", None)
                if isinstance(nid, int) and nid >= 256:
                    ids.add(nid)
        ref[ss_num] = ids
    return ref


class AuditNameTableManager:
    """Enhanced name table manager for audit/repair that avoids STAT/fvar conflicts."""

    def __init__(self, font):
        self.font = font
        self.name_table = font["name"]

    def has_windows_record(self, name_id):
        return has_windows_name_id(self.name_table, name_id)

    def get_name_strings(self, name_id):
        return list(get_name_strings_by_id(self.name_table, name_id))

    def add_name_record(self, name_id, text):
        """Add Windows/English name table record."""
        self.name_table.setName(text, name_id, 3, 1, 0x0409)

    def allocate_unique_id(self, exclude_ids=None):
        """Allocate unique nameID avoiding STAT/fvar/other feature conflicts."""
        if exclude_ids is None:
            exclude_ids = set()
        existing = {rec.nameID for rec in self.name_table.names}
        reserved = existing | exclude_ids | collect_used_name_ids(self.font)
        candidate = 256
        while candidate in reserved:
            candidate += 1
        return candidate

    def overwrite_label(self, name_id, new_label):
        """Overwrite existing label."""
        self.add_name_record(name_id, new_label)


class FeatureParamsFixer:
    """Fixes FeatureParams for stylistic sets."""

    def __init__(self, font):
        self.font = font
        self.names = AuditNameTableManager(font)

    def ensure_feature_params(
        self, records, ss_num, fix, add_missing_params, pretend, report
    ):
        """Ensure FeatureParams exist for all records."""
        changed_any = False
        planned_any = False
        created_params = 0
        missing_count = sum(
            1
            for frec in records
            if getattr(frec.Feature, "FeatureParams", None) is None
        )
        if missing_count > 0 and not (add_missing_params and (fix or pretend)):
            report.append(
                f"ss{ss_num:02d}: FeatureParams absent across {missing_count}"
            )
        if fix and add_missing_params and missing_count > 0:
            for frec in records:
                if getattr(frec.Feature, "FeatureParams", None) is None:
                    params = otTables.FeatureParamsStylisticSet()
                    params.Version = 0
                    params.UINameID = None
                    frec.Feature.FeatureParams = params
                    changed_any = True
                    created_params += 1
        if created_params:
            report.append(
                f"CREATED ss{ss_num:02d}: FeatureParams for {created_params} record(s) (Version=0)"
            )
        elif (
            pretend
            and add_missing_params
            and any(getattr(f.Feature, "FeatureParams", None) is None for f in records)
        ):
            planned_any = True
            missing = sum(
                1 for f in records if getattr(f.Feature, "FeatureParams", None) is None
            )
            report.append(
                f"ss{ss_num:02d}: will add FeatureParams with Version=0 for {missing} record(s)"
            )

        params_list = [getattr(f.Feature, "FeatureParams", None) for f in records]
        params_list = [p for p in params_list if p is not None]
        return params_list, changed_any, planned_any

    def normalize_versions(self, params_list, ss_num, fix, report):
        """Normalize Version fields to 0."""
        changed_any = False
        for p in params_list:
            if getattr(p, "Version", 0) != 0:
                report.append(f"ss{ss_num:02d}: Version={p.Version} -> 0")
                if fix:
                    p.Version = 0
                    changed_any = True
        return changed_any

    def overwrite_label(
        self, target_id, ss_num, set_labels, overwrite_labels, fix, pretend, report
    ):
        """Overwrite label if requested."""
        if target_id is None or not (set_labels and ss_num in set_labels):
            return False, False
        desired = set_labels[ss_num]
        existing_samples = self.names.get_name_strings(target_id)
        current = existing_samples[0] if existing_samples else None
        if overwrite_labels or current is None:
            if current != desired:
                if fix:
                    self.names.overwrite_label(target_id, desired)
                    report.append(
                        f"UPDATED ss{ss_num:02d}: label {current!r} -> {desired!r} (nameID {target_id})"
                    )
                    return True, False
                else:
                    report.append(
                        f"UPDATED ss{ss_num:02d}: label {current!r} -> {desired!r} (nameID {target_id})"
                    )
                    return False, True
        return False, False

    def apply_target_id(self, params_list, target_id, ss_num, fix, pretend, set_labels):
        """Apply target UINameID to all params."""
        report_lines = []
        changed_any = False
        planned_any = False
        if target_id is None:
            return report_lines, changed_any, planned_any
        changes = 0
        sets = 0
        overwrites = 0
        for p in params_list:
            cur = getattr(p, "UINameID", None)
            if cur != target_id:
                changes += 1
                if isinstance(cur, int) and cur >= 0:
                    overwrites += 1
                else:
                    sets += 1
                if not pretend:
                    if fix:
                        p.UINameID = target_id
                        changed_any = True
        total = len(params_list)
        if changes:
            planned_any = True
            summary = []
            if sets:
                summary.append(f"set {sets}")
            if overwrites:
                summary.append(f"overwrite {overwrites}")
            summary_str = ", ".join(summary) if summary else "updated"
            report_lines.append(
                f"UPDATED ss{ss_num:02d}: UINameID -> {target_id} ({summary_str}, total {total})"
            )
        else:
            samples = self.names.get_name_strings(target_id)
            if samples:
                name_str = f"'{samples[0]}'"
            else:
                if pretend and set_labels and ss_num in set_labels:
                    name_str = f"'{set_labels[ss_num]}' (planned)"
                else:
                    name_str = "<no name>"
            report_lines.append(
                f"UNCHANGED ss{ss_num:02d}: UINameID {target_id}, label {name_str} across {len(params_list)}"
            )
        return report_lines, changed_any, planned_any


class NameIDResolver:
    """Resolves and allocates UINameIDs for stylistic sets."""

    def __init__(self, font):
        self.font = font
        self.names = AuditNameTableManager(font)
        self.usage = {}
        self.referenced_by_ss = {}

    def _ensure_label(self, ss_num, name_id, set_labels, fix, pretend, report):
        """Ensure label exists for nameID."""
        if not self.names.has_windows_record(name_id):
            if set_labels and ss_num in set_labels:
                label = set_labels[ss_num]
            else:
                label = f"Stylistic Set {ss_num:02d}"
            if fix:
                self.names.add_name_record(name_id, label)
            report.append(f"CREATED ss{ss_num:02d}: nameID {name_id} -> '{label}'")
            return True
        return False

    def resolve(
        self,
        ss_num,
        params_list,
        set_labels=None,
        pretend=False,
        fix=False,
    ):
        """Resolve target UINameID for a stylistic set."""
        report = []
        changed_any = False
        planned_any = False
        flagged_any = False

        name_table = self.names.name_table
        group_ref_ids = {
            getattr(p, "UINameID", None)
            for p in params_list
            if isinstance(getattr(p, "UINameID", None), int)
            and getattr(p, "UINameID", None) >= 256
        }
        valid_in_group = [
            nid for nid in group_ref_ids if has_windows_name_id(name_table, nid)
        ]

        target_id = None

        # 1) reuse valid within group
        if target_id is None and valid_in_group:
            target_id = sorted(valid_in_group)[0]

        # 2) use referenced id creating missing record if not colliding
        elif target_id is None and group_ref_ids:
            candidate = sorted(group_ref_ids)[0]
            colliding = [
                other
                for other, ids in self.referenced_by_ss.items()
                if other != ss_num and candidate in ids
            ]
            if colliding:
                report.append(
                    f"ss{ss_num:02d}: referenced UINameID={candidate} also used by ss{colliding[0]:02d}"
                )
                report.append(
                    f"FLAG: ss{ss_num:02d} conflicting reference to nameID {candidate}"
                )
                flagged_any = True
            else:
                if (fix or pretend) and not self.names.has_windows_record(candidate):
                    chg = self._ensure_label(
                        ss_num, candidate, set_labels, fix, pretend, report
                    )
                    if fix:
                        changed_any |= chg
                    else:
                        planned_any |= chg
                target_id = candidate

        # 3) allocate new
        if target_id is None:
            exclude = set().union(
                *(ids for s, ids in self.referenced_by_ss.items() if s != ss_num)
            ) | set(self.usage.keys())
            target_id = self.names.allocate_unique_id(exclude_ids=exclude)
            if set_labels and ss_num in set_labels:
                label = set_labels[ss_num]
            else:
                label = f"Stylistic Set {ss_num:02d}"
            if fix or pretend:
                if fix:
                    self.names.add_name_record(target_id, label)
                    changed_any = True
                else:
                    planned_any = True
            samples = self.names.get_name_strings(target_id)
            name_str = f"'{samples[0]}'" if samples else f"'{label}'"
            report.append(
                f"CREATED ss{ss_num:02d}: allocate NameID {target_id} {name_str}"
            )

        return target_id, report, changed_any, planned_any, flagged_any


def audit_and_repair_stylistic_sets(
    font_path: str,
    fix: bool = False,
    add_missing_params: bool = False,
    set_labels: Optional[Dict[int, str]] = None,
    force_overwrite: bool = False,
    pretend: bool = False,
) -> Tuple[List[str], bool, bool]:
    """Audit and optionally repair stylistic sets in a font."""
    report = []
    changed_any = False
    flagged_any = False

    try:
        font = TTFont(font_path)
    except Exception as e:
        return [f"Failed to open font: {e}"], False, False

    if "GSUB" not in font:
        report.append("No GSUB table; nothing to do.")
        font.close()
        return report, changed_any, flagged_any

    # Collect stylistic set groups
    ss_groups = collect_ss_feature_records_by_number(font["GSUB"])
    if not ss_groups:
        report.append("No ss01–ss20 features found.")
        font.close()
        return report, changed_any, flagged_any

    # Pre-compute referenced UINameIDs by ss to avoid collisions
    referenced_by_ss = collect_referenced_ui_name_ids_by_ss(ss_groups)
    usage = collect_name_id_usage(font)

    fixer = FeatureParamsFixer(font)
    label_map = dict(set_labels or {})

    for ss_num, records in sorted(ss_groups.items(), key=lambda x: x[0]):
        # Ensure FeatureParams exist
        params_list, created_changed, created_planned = fixer.ensure_feature_params(
            records, ss_num, fix, add_missing_params, pretend, report
        )
        if created_changed:
            changed_any = True
        if not params_list:
            continue

        # Fix Version across the group
        if fixer.normalize_versions(params_list, ss_num, fix, report):
            changed_any = True

        # Determine target UINameID via resolver
        resolver = NameIDResolver(font)
        resolver.usage = usage
        resolver.referenced_by_ss = referenced_by_ss
        target_id, rlines, rchanged, rplanned, rflagged = resolver.resolve(
            ss_num,
            params_list,
            set_labels=label_map,
            pretend=pretend,
            fix=fix,
        )
        report.extend(rlines)
        if rchanged:
            changed_any = True
        if rflagged:
            flagged_any = True

        # Overwrite label if requested
        overwrite_policy = force_overwrite
        ol_changed, ol_planned = fixer.overwrite_label(
            target_id, ss_num, label_map, overwrite_policy, fix, pretend, report
        )
        if ol_changed:
            changed_any = True

        # Apply target_id across the entire group
        rlines, rchg, rplan = fixer.apply_target_id(
            params_list, target_id, ss_num, fix, pretend, label_map
        )
        report.extend(rlines)
        if rchg:
            changed_any = True

    if fix and changed_any:
        try:
            font.save(font_path)
            report.append(f"Saved: {font_path}")
        except Exception as e:
            report.append(f"Failed to save: {e}")

    font.close()
    if pretend:
        changed_any = any("CREATED" in r or "UPDATED" in r for r in report)
    return report, changed_any, flagged_any


# ============================================================================
# WRAPPER FUNCTIONALITY (Table Scaffolding)
# ============================================================================


def _derive_unicode_map_from_glyph_names(font: TTFont) -> Dict[int, str]:
    """Derive a Unicode mapping from glyph names using AGL rules."""
    from opentype_features.opentype_features_config import CONFIG

    mapping: Dict[int, str] = {}
    for glyph_name in font.getGlyphOrder():
        if glyph_name in CONFIG.SPECIAL_GLYPHS:
            continue
        try:
            uni = toUnicode(glyph_name)
        except Exception:
            uni = None
        if not uni:
            continue
        if len(uni) != 1:
            continue
        cp = ord(uni)
        if cp not in mapping:
            mapping[cp] = glyph_name
    return mapping


def _font_has_windows_unicode_cmap(font: TTFont) -> bool:
    """Check if font has Windows Unicode cmap."""
    if "cmap" not in font:
        return False
    try:
        for sub in font["cmap"].tables:
            if sub.platformID == 3 and sub.platEncID in (1, 10):
                if getattr(sub, "cmap", None):
                    return True
    except Exception:
        return False
    return False


def ensure_cmap(
    font: TTFont, overwrite_unicode: bool = False
) -> Tuple[bool, List[str]]:
    """Ensure a Windows Unicode cmap exists."""
    messages: List[str] = []

    existing_best = {}
    try:
        existing_best = font.getBestCmap() or {}
    except Exception:
        existing_best = {}

    if existing_best and not overwrite_unicode and _font_has_windows_unicode_cmap(font):
        messages.append("Unicode cmap present; no change")
        return False, messages

    derived = _derive_unicode_map_from_glyph_names(font)
    if existing_best:
        for cp, g in existing_best.items():
            derived.setdefault(cp, g)

    if not derived:
        messages.append("Unable to derive any Unicode mapping from glyph names")
        return False, messages

    need_u32 = any(cp > 0xFFFF for cp in derived)

    if "cmap" not in font or overwrite_unicode:
        cmap_table = newTable("cmap")
        cmap_table.tableVersion = 0
        cmap_table.tables = []
    else:
        cmap_table = font["cmap"]
        if overwrite_unicode:
            cmap_table.tables = [
                st
                for st in cmap_table.tables
                if not (st.platformID == 3 and st.platEncID in (1, 10))
            ]

    bmp_map = {cp: g for cp, g in derived.items() if cp <= 0xFFFF}
    if bmp_map:
        st4 = CmapSubtable.newSubtable(4)
        st4.platformID = 3
        st4.platEncID = 1
        st4.language = 0
        st4.cmap = bmp_map
        cmap_table.tables.append(st4)

    if need_u32:
        st12 = CmapSubtable.newSubtable(12)
        st12.platformID = 3
        st12.platEncID = 10
        st12.language = 0
        st12.cmap = derived
        cmap_table.tables.append(st12)

    font["cmap"] = cmap_table
    messages.append(
        (
            "Created Unicode cmap (format 4" + (" + 12" if need_u32 else "") + ")"
            if "cmap" not in font
            or overwrite_unicode
            or not _font_has_windows_unicode_cmap(font)
            else "Added Windows Unicode subtable(s)"
        )
    )
    return True, messages


def ensure_gdef(font: TTFont, overwrite: bool = False) -> Tuple[bool, str]:
    """Ensure GDEF table exists."""
    if "GDEF" in font and not overwrite:
        return False, "GDEF present; no change"
    gdef = newTable("GDEF")
    gdef.table = otTables.GDEF()
    gdef.table.Version = 0x00010000
    gdef.table.GlyphClassDef = None
    gdef.table.AttachList = None
    gdef.table.LigCaretList = None
    gdef.table.MarkAttachClassDef = None
    gdef.table.MarkGlyphSetsDef = None
    font["GDEF"] = gdef
    return True, "Created empty GDEF"


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


def ensure_gpos(font: TTFont, overwrite: bool = False) -> Tuple[bool, str]:
    """Ensure GPOS table exists."""
    if "GPOS" in font and not overwrite:
        return False, "GPOS present; no change"
    gpos = newTable("GPOS")
    gpos.table = _empty_otl_table(otTables.GPOS)
    font["GPOS"] = gpos
    return True, "Created empty GPOS"


def ensure_gsub(font: TTFont, overwrite: bool = False) -> Tuple[bool, str]:
    """Ensure GSUB table exists."""
    if "GSUB" in font and not overwrite:
        return False, "GSUB present; no change"
    gsub = newTable("GSUB")
    gsub.table = _empty_otl_table(otTables.GSUB)
    font["GSUB"] = gsub
    return True, "Created empty GSUB"


def ensure_dsig_stub(font: TTFont, enable: bool) -> Tuple[bool, str]:
    """Ensure DSIG stub exists."""
    if not enable:
        return False, "DSIG disabled"
    if "DSIG" in font:
        return False, "DSIG present; no change"
    dsig = newTable("DSIG")
    dsig.ulVersion = 1
    dsig.usFlag = 0
    dsig.usNumSigs = 0
    dsig.signatureRecords = []
    font["DSIG"] = dsig
    return True, "Created DSIG stub"


def _invert_best_cmap(font: TTFont) -> Dict[str, List[int]]:
    """Return mapping glyphName -> list of codepoints from best cmap."""
    inv: Dict[str, List[int]] = {}
    try:
        best = font.getBestCmap() or {}
    except Exception:
        best = {}
    for cp, gname in best.items():
        inv.setdefault(gname, []).append(cp)
    return inv


def _detect_mark_glyphs(font: TTFont) -> Set[str]:
    """Detect mark glyphs by Unicode categories."""
    inv = _invert_best_cmap(font)
    marks: Set[str] = set()
    for g, cps in inv.items():
        for cp in cps:
            cat = unicodedata.category(chr(cp))
            if cat in ("Mn", "Mc", "Me"):
                marks.add(g)
                break
    for g in font.getGlyphOrder():
        lower = g.lower()
        if any(tok in lower for tok in ("comb", "mark")):
            marks.add(g)
    return marks


def _parse_ligature_components(glyph_name: str, font: TTFont) -> List[str]:
    """Infer base component glyph names from a ligature glyph name."""
    base = glyph_name.split(".")[0]
    if "_" in base:
        parts = base.split("_")
    else:
        if len(base) == 2 and all(ch.isalpha() for ch in base):
            parts = [base[0], base[1]]
        else:
            return []

    best = font.getBestCmap() or {}
    cp_to_g = best

    resolved: List[str] = []
    for p in parts:
        if p.startswith("uni") and len(p) >= 7:
            hexpart = p[3:7]
            try:
                cp = int(hexpart, 16)
            except Exception:
                return []
            gname = cp_to_g.get(cp)
            if not gname:
                return []
            resolved.append(gname)
        else:
            if p in font.getGlyphOrder():
                resolved.append(p)
            else:
                return []
    return resolved if len(resolved) >= 2 else []


def infer_ligatures(font: TTFont) -> List[Tuple[List[str], str]]:
    """Return list of ([components...], ligatureGlyphName)."""
    ligs: List[Tuple[List[str], str]] = []
    go = set(font.getGlyphOrder())
    for g in go:
        comps = _parse_ligature_components(g, font)
        if comps:
            ligs.append((comps, g))
    return ligs


def build_liga_feature_text(font: TTFont, ligs: List[Tuple[List[str], str]]) -> str:
    """Build liga feature text."""
    lines = ["feature liga {"]
    for comps, lig in ligs:
        lines.append(f"  sub {' '.join(comps)} by {lig};")
    lines.append("} liga;")
    return "\n".join(lines)


def build_kern_feature_text(font: TTFont) -> Optional[str]:
    """Build kern feature text from legacy kern table."""
    if "kern" not in font:
        return None
    try:
        k = font["kern"]
        subtables = getattr(k, "kernTables", None) or getattr(k, "tables", None)
    except Exception:
        return None
    if not subtables:
        return None
    rules: List[str] = []
    for st in subtables:
        try:
            if getattr(st, "format", 0) != 0:
                continue
            table = getattr(st, "kernTable", None)
            if not table:
                continue
            for (left_glyph, right_glyph), val in table.items():
                if not isinstance(left_glyph, str) or not isinstance(right_glyph, str):
                    try:
                        left_glyph = font.getGlyphOrder()[left_glyph]
                        right_glyph = font.getGlyphOrder()[right_glyph]
                    except Exception:
                        continue
                if val == 0:
                    continue
                rules.append(f"  pos {left_glyph} {right_glyph} {val};")
        except Exception:
            continue
    if not rules:
        return None
    return "\n".join(["feature kern {", *rules, "} kern;"])


def apply_feature_text(font: TTFont, feature_text: str) -> Tuple[bool, str]:
    """Apply feature text to font."""
    if not feature_text:
        return False, ""
    if not HAVE_FEALIB:
        return False, "feaLib not available; cannot build features"
    try:
        addOpenTypeFeaturesFromString(font, feature_text)
        return True, "features compiled"
    except Exception as e:
        return False, f"feature build failed: {e}"


try:
    from fontTools.otlLib.builder import buildGDEF as _buildGDEF

    HAVE_BUILDGDEF = True
except Exception:
    HAVE_BUILDGDEF = False
    _buildGDEF = None


def build_enriched_gdef(
    font: TTFont, use_classes: bool, add_carets: bool
) -> Tuple[bool, str]:
    """Build enriched GDEF with classes and carets."""
    if not use_classes and not add_carets:
        return False, "GDEF enrichment disabled"

    class_map: Dict[str, int] = {}
    carets: Dict[str, List[int]] = {}

    marks = _detect_mark_glyphs(font) if use_classes else set()
    ligs = infer_ligatures(font) if (use_classes or add_carets) else []
    lig_set = {lig for _, lig in ligs}

    if use_classes:
        for g in font.getGlyphOrder():
            if g in marks:
                class_map[g] = 3  # Mark
            elif g in lig_set:
                class_map[g] = 2  # Ligature
            else:
                class_map[g] = 1  # Base

    if add_carets and ligs:
        hmtx = font["hmtx"]
        for comps, lig in ligs:
            try:
                adv = hmtx[lig][0]
            except Exception:
                continue
            n = len(comps)
            if n >= 2 and adv > 0:
                carets[lig] = [int(adv * i / n) for i in range(1, n)]

    if not class_map and not carets:
        return False, "No GDEF data inferred"

    if HAVE_BUILDGDEF and _buildGDEF is not None:
        try:
            mark_sets = [marks] if marks else None
            gdef_table = _buildGDEF(
                glyphClassDef=class_map or None,
                attachList=None,
                ligCaretList=carets or None,
                markAttachClassDef=None,
                markGlyphSetsDef=mark_sets,
            )
            gdef = newTable("GDEF")
            gdef.table = gdef_table
            font["GDEF"] = gdef
            return True, "Enriched GDEF built"
        except Exception as e:
            return False, f"Failed to build enriched GDEF: {e}"
    else:
        try:
            gdef = newTable("GDEF")
            gdef.table = otTables.GDEF()
            gdef.table.Version = 0x00010000
            if class_map:
                cd = otTables.ClassDef()
                cd.classDefs = class_map
                gdef.table.GlyphClassDef = cd
            if carets:
                lcl = otTables.LigCaretList()
                lcl.LigGlyphCount = len(carets)
                lcl.LigGlyph = []
                cov = otTables.Coverage()
                cov.glyphs = list(carets.keys())
                lcl.Coverage = cov
                for lig, caret_positions in carets.items():
                    lg = otTables.LigGlyph()
                    lg.CaretCount = len(caret_positions)
                    lg.CaretValue = []
                    for x in caret_positions:
                        cv = otTables.CaretValue()
                        cv.Format = 1
                        cv.Coordinate = x
                        lg.CaretValue.append(cv)
                    lcl.LigGlyph.append(lg)
                gdef.table.LigCaretList = lcl
            font["GDEF"] = gdef
            return True, "Enriched GDEF (fallback) built"
        except Exception as e:
            return False, f"Failed to build enriched GDEF fallback: {e}"


def enrich_font(
    font: TTFont,
    do_kern_migration: bool,
    do_liga: bool,
    do_gdef_classes: bool,
    do_lig_carets: bool,
    drop_kern_after: bool,
) -> Tuple[bool, List[str]]:
    """Enrich font with inferred features."""
    changed = False
    messages: List[str] = []

    if do_kern_migration:
        fea = build_kern_feature_text(font)
        if fea:
            ok, msg = apply_feature_text(font, fea)
            messages.append("kern→GPOS: " + ("ok" if ok else msg))
            changed = changed or ok
            if ok and drop_kern_after and "kern" in font:
                try:
                    del font["kern"]
                    messages.append("Dropped legacy 'kern' table")
                    changed = True
                except Exception:
                    messages.append("Failed to drop 'kern' table")
        else:
            messages.append("No legacy 'kern' data found")

    if do_liga:
        ligs = infer_ligatures(font)
        if ligs:
            fea = build_liga_feature_text(font, ligs)
            ok, msg = apply_feature_text(font, fea)
            messages.append("liga GSUB: " + ("ok" if ok else msg))
            changed = changed or ok
        else:
            messages.append("No ligatures inferred from names")

    if do_gdef_classes or do_lig_carets:
        ok, msg = build_enriched_gdef(
            font, use_classes=do_gdef_classes, add_carets=do_lig_carets
        )
        messages.append(msg)
        changed = changed or ok

    return changed, messages


def process_wrapper_font(
    filepath: str,
    overwrite_cmap: bool,
    add_dsig: bool,
    overwrite_gdef: bool,
    overwrite_gpos: bool,
    overwrite_gsub: bool,
    do_enrich: bool,
    enrich_no_kern_migration: bool,
    enrich_no_liga: bool,
    enrich_no_gdef_classes: bool,
    enrich_no_lig_carets: bool,
    drop_kern: bool,
) -> Tuple[bool, List[str]]:
    """Process a font with wrapper functionality (legacy function)."""
    try:
        font = TTFont(filepath)
    except Exception as e:
        return False, [f"Failed to open font: {e}"]

    changes: List[str] = []
    any_changed = False

    changed, msgs = ensure_cmap(font, overwrite_unicode=overwrite_cmap)
    if changed:
        any_changed = True
    changes.extend(msgs)

    changed, msg = ensure_gdef(font, overwrite=overwrite_gdef)
    if changed:
        any_changed = True
    changes.append(msg)

    changed, msg = ensure_gpos(font, overwrite=overwrite_gpos)
    if changed:
        any_changed = True
    changes.append(msg)

    changed, msg = ensure_gsub(font, overwrite=overwrite_gsub)
    if changed:
        any_changed = True
    changes.append(msg)

    changed, msg = ensure_dsig_stub(font, enable=add_dsig)
    if changed:
        any_changed = True
    changes.append(msg)

    if do_enrich:
        e_changed, e_msgs = enrich_font(
            font,
            do_kern_migration=not enrich_no_kern_migration,
            do_liga=not enrich_no_liga,
            do_gdef_classes=not enrich_no_gdef_classes,
            do_lig_carets=not enrich_no_lig_carets,
            drop_kern_after=drop_kern,
        )
        if e_changed:
            any_changed = True
        changes.extend(e_msgs)

    if any_changed:
        try:
            font.save(filepath)
            changes.append(f"Saved: {filepath}")
        except Exception as e:
            return False, [f"Failed to save font: {e}"]
        return True, changes
    else:
        return False, ["No changes needed"]


def process_wrapper_font_v2(
    filepath: str,
    user_prefs: dict,
    dry_run: bool = False,
) -> OperationResult:
    """
    Process font with wrapper functionality (v2 - validation-first).

    Args:
        filepath: Path to font file
        user_prefs: User preferences dict
        dry_run: If True, only show what would be done

    Returns:
        OperationResult with all messages and success status
    """
    result = OperationResult(success=True)

    try:
        font = TTFont(filepath)
    except Exception as e:
        result.add_error(f"Failed to open font: {e}")
        return result

    # Always validate first
    validator = FontValidator(font)
    strategy_engine = WrapperStrategyEngine(font, validator)

    # Create plan
    plan, plan_result = strategy_engine.create_plan(user_prefs)
    result.messages.extend(plan_result.messages)

    if not plan_result.success:
        result.success = False
        result.add_error(
            "Validation failed",
            "Cannot proceed with wrapper operations. Fix issues or use --skip-validation.",
        )
        font.close()
        return result

    if not plan.has_work():
        result.add_info("No wrapper operations needed")
        font.close()
        return result

    if dry_run:
        result.add_info("DRY RUN - would perform:", plan.summarize())
        font.close()
        return result

    # Execute plan
    try:
        executor = WrapperExecutor(font, plan)
        exec_result, has_changes = executor.execute()
        result.messages.extend(exec_result.messages)

        if exec_result.success:
            # Sort Coverage tables if GSUB/GPOS tables exist
            # (sort even if no other changes, in case tables already had unsorted Coverage)
            if "GSUB" in font or "GPOS" in font:
                try:
                    total, sorted_count = sort_coverage_tables_in_font(
                        font, verbose=False
                    )
                    if sorted_count > 0:
                        result.add_info(
                            f"Sorted {sorted_count} of {total} Coverage table(s)"
                        )
                except Exception as e:
                    result.add_error(
                        f"Failed to sort Coverage tables: {e}",
                        "Font will be saved but Coverage tables may not be sorted",
                    )

            # Only save if actual changes were made
            if has_changes:
                font.save(filepath)
                result.add_info(f"Saved: {filepath}")
            else:
                result.add_info("No changes needed - font already has required tables")
        else:
            result.success = False

    except Exception as e:
        result.add_error(f"Execution failed: {e}")
        result.success = False
    finally:
        font.close()

    return result


# ============================================================================
# FONT PROCESSOR
# ============================================================================


class FontProcessor:
    """Main processor for analyzing and adding features to fonts."""

    def __init__(
        self,
        font_path: str,
        apply_features: bool = False,
        selected_features: Optional[Set[str]] = None,
        preserve_existing: bool = True,
        ss_labels: Optional[Dict[int, str]] = None,
        dry_run: bool = False,
        optimize: bool = False,
        enable_positioning: bool = False,
        apply_kern_repair: bool = False,
    ):
        self.font_path = font_path
        self.apply_features = apply_features
        self.selected_features = selected_features
        self.preserve_existing = preserve_existing
        self.ss_labels = ss_labels
        self.dry_run = dry_run
        self.optimize = optimize
        self.enable_positioning = enable_positioning
        self.apply_kern_repair = apply_kern_repair

    def process(self) -> bool:
        """Process the font file."""
        try:
            cs.StatusIndicator("parsing").add_file(
                self.font_path, filename_only=False
            ).emit()

            font = TTFont(self.font_path)

            # Detect all feature patterns
            detector = GlyphPatternDetector(font)
            detected = detector.detect_all_features()

            # Analyze mode: just report what was found
            if not self.apply_features:
                return self._analyze_mode(detected)

            # Apply mode: generate and add features
            return self._apply_mode(font, detected)

        except Exception as e:
            cs.StatusIndicator("error").add_file(
                self.font_path, filename_only=False
            ).with_explanation(str(e)).emit()
            return False

    def _analyze_mode(self, detected: Dict[str, any]) -> bool:
        """Analyze and report detected features without modifying."""
        cs.StatusIndicator("info").add_file(
            self.font_path, filename_only=True
        ).add_message("Feature Analysis").emit()

        has_features = False

        # Ligatures
        if detected["liga"]:
            has_features = True
            count = len(detected["liga"])
            glyphs = [lig[1] for lig in detected["liga"][:5]]
            preview = ", ".join(glyphs)
            if count > 5:
                preview += f", ... ({count - 5} more)"

            cs.StatusIndicator("discovered").add_message(
                f"Standard Ligatures: {count} glyphs"
            ).with_explanation(preview).emit()

        # Stylistic sets
        if detected["stylistic_sets"]:
            has_features = True
            sets = detected["stylistic_sets"]
            cs.StatusIndicator("discovered").add_message(
                f"Stylistic Sets: {len(sets)} sets detected"
            ).emit()

            # Create temp manager to generate suggested labels
            temp_font = TTFont(self.font_path)
            ss_manager = StylisticSetManager(temp_font)

            for ss_num in sorted(sets.keys())[:10]:
                glyphs = sets[ss_num]
                preview = ", ".join([f"{base}→{alt}" for base, alt in glyphs[:3]])
                if len(glyphs) > 3:
                    preview += f" ... ({len(glyphs) - 3} more)"

                # Generate suggested label
                suggested_label = ss_manager.generate_label_from_glyphs(ss_num, glyphs)

                cs.emit(
                    f'{cs.indent(1)}ss{ss_num:02d}: {len(glyphs)} glyphs — "{suggested_label}"'
                )
                cs.emit(f"{cs.indent(2)}{preview}")

        # Small caps
        if detected["smcp"]:
            has_features = True
            count = len(detected["smcp"])
            cs.StatusIndicator("discovered").add_message(
                f"Small Caps: {count} glyphs"
            ).emit()

        # Figure variants
        for feature_tag in ["onum", "lnum", "tnum", "pnum"]:
            if detected[feature_tag]:
                has_features = True
                count = len(detected[feature_tag])
                feature_names = {
                    "onum": "Old-style Figures",
                    "lnum": "Lining Figures",
                    "tnum": "Tabular Figures",
                    "pnum": "Proportional Figures",
                }
                cs.StatusIndicator("discovered").add_message(
                    f"{feature_names[feature_tag]}: {count} glyphs"
                ).emit()

        # Swashes
        if detected["swsh"]:
            has_features = True
            count = len(detected["swsh"])
            cs.StatusIndicator("discovered").add_message(
                f"Swashes: {count} glyphs"
            ).emit()

        # Discretionary ligatures
        if detected["dlig"]:
            has_features = True
            count = len(detected["dlig"])
            cs.StatusIndicator("discovered").add_message(
                f"Discretionary Ligatures: {count} glyphs"
            ).emit()

        # Contextual alternates
        if detected["calt"]:
            has_features = True
            count = len(detected["calt"])
            cs.StatusIndicator("discovered").add_message(
                f"Contextual Alternates: {count} glyphs"
            ).emit()

        if not has_features:
            cs.StatusIndicator("info").add_message(
                "No OpenType features detected from glyph names"
            ).emit()

        cs.emit("")
        return True

    def _deduplicate_fea_code(self, fea_code: str) -> tuple[str, set]:
        """Remove duplicate substitution rules from FEA code.

        This handles cases where the same substitution appears in multiple features,
        which can happen during feature extraction from complex fonts.

        Key insight: The same component sequence can't appear twice in GSUB,
        regardless of what it maps to. So we only track components, not targets.
        """
        lines = fea_code.split("\n")
        seen_components = set()
        deduped_lines = []
        removed_count = 0
        duplicates_found = []  # Track duplicates for debugging

        for line in lines:
            # Check if this is a substitution rule
            # Use stricter pattern to avoid false matches
            stripped_line = line.strip()
            if (
                stripped_line.startswith("sub ")
                and " by " in stripped_line
                and stripped_line.endswith(";")
            ):
                # Extract the components (everything between "sub" and "by")
                match = re.match(r"^\s*sub\s+(.+?)\s+by\s+(.+?);", line)
                if match:
                    components_str = match.group(1).strip()
                    target_str = match.group(2).strip()
                    # Normalize whitespace: replace any sequence of whitespace with single space
                    normalized_components_str = re.sub(r"\s+", " ", components_str)
                    components = tuple(normalized_components_str.split(" "))

                    if components in seen_components:
                        # Skip this duplicate
                        removed_count += 1
                        duplicates_found.append(
                            f"{' '.join(components)} → {target_str}"
                        )
                        continue
                    seen_components.add(components)

            deduped_lines.append(line)

        if removed_count > 0:
            cs.StatusIndicator("info").add_message(
                f"Removed {removed_count} duplicate substitution(s) from existing features"
            ).emit()
            # Show first few duplicates for debugging
            if duplicates_found:
                cs.StatusIndicator("info").add_message(
                    f"First few duplicates: {', '.join(duplicates_found[:5])}"
                ).emit()

        # Extract ligature sequences from FEA for filtering
        fea_ligature_sequences = set()
        for comp_tuple in seen_components:
            if len(comp_tuple) >= 2:  # Only ligatures (2+ components)
                fea_ligature_sequences.add(comp_tuple)

        if fea_ligature_sequences:
            cs.StatusIndicator("info").add_message(
                f"Found {len(fea_ligature_sequences)} ligature sequences in FEA code"
            ).emit()

        return "\n".join(deduped_lines), fea_ligature_sequences

    def _filter_against_existing(
        self, detected: Dict[str, any], existing_subs: Dict[str, Set]
    ) -> Dict[str, any]:
        """
        Filter detected features against existing substitutions to avoid duplicates.

        Args:
            detected: Dictionary of detected features from GlyphPatternDetector
            existing_subs: Dictionary with 'ligatures' and 'single' sets from ExistingSubstitutionExtractor

        Returns:
            Filtered dictionary with same structure as detected, but with duplicates removed
        """
        filtered = {}
        existing_ligatures = existing_subs.get("ligatures", set())
        existing_single = existing_subs.get("single", set())

        # Filter ligatures (liga, dlig)
        # Format: list of ([components...], lig_glyph) tuples
        for ligature_tag in ["liga", "dlig"]:
            if ligature_tag in detected:
                filtered_ligs = []
                for components, lig_glyph in detected[ligature_tag]:
                    # Convert components list to tuple for comparison
                    comp_tuple = tuple(components)
                    if comp_tuple not in existing_ligatures:
                        filtered_ligs.append((components, lig_glyph))
                filtered[ligature_tag] = filtered_ligs
            else:
                filtered[ligature_tag] = []

        # Filter single substitutions (smcp, onum, lnum, tnum, pnum, swsh, calt)
        # Format: list of (base_glyph, variant_glyph) tuples
        for single_tag in ["smcp", "onum", "lnum", "tnum", "pnum", "swsh", "calt"]:
            if single_tag in detected:
                filtered_subs = [
                    (base, alt)
                    for base, alt in detected[single_tag]
                    if (base, alt) not in existing_single
                ]
                filtered[single_tag] = filtered_subs
            else:
                filtered[single_tag] = []

        # Filter Phase 1 single substitutions (sups, subs, ordn, c2sc, salt, zero, case, titl)
        for single_tag in [
            "sups",
            "subs",
            "ordn",
            "c2sc",
            "salt",
            "zero",
            "case",
            "titl",
        ]:
            if single_tag in detected:
                filtered_subs = [
                    (base, alt)
                    for base, alt in detected[single_tag]
                    if (base, alt) not in existing_single
                ]
                filtered[single_tag] = filtered_subs
            else:
                filtered[single_tag] = []

        # Filter Phase 2 single substitutions (numr, dnom, sinf, hist)
        for single_tag in ["numr", "dnom", "sinf", "hist"]:
            if single_tag in detected:
                filtered_subs = [
                    (base, alt)
                    for base, alt in detected[single_tag]
                    if (base, alt) not in existing_single
                ]
                filtered[single_tag] = filtered_subs
            else:
                filtered[single_tag] = []

        # Filter fractions (special structure: dict with numerators/denominators)
        if "frac" in detected:
            frac_data = detected["frac"]
            if isinstance(frac_data, dict):
                filtered_frac = {
                    "numerators": [
                        (base, alt)
                        for base, alt in frac_data.get("numerators", [])
                        if (base, alt) not in existing_single
                    ],
                    "denominators": [
                        (base, alt)
                        for base, alt in frac_data.get("denominators", [])
                        if (base, alt) not in existing_single
                    ],
                }
                filtered["frac"] = filtered_frac
            else:
                filtered["frac"] = {"numerators": [], "denominators": []}
        else:
            filtered["frac"] = {"numerators": [], "denominators": []}

        # Filter stylistic sets
        # Format: dict of {ss_num: [(base_glyph, variant_glyph), ...]}
        if "stylistic_sets" in detected:
            filtered_ss = {}
            for ss_num, substitutions in detected["stylistic_sets"].items():
                filtered_ss_subs = [
                    (base, alt)
                    for base, alt in substitutions
                    if (base, alt) not in existing_single
                ]
                if filtered_ss_subs:  # Only include if there are substitutions left
                    filtered_ss[ss_num] = filtered_ss_subs
            filtered["stylistic_sets"] = filtered_ss
        else:
            filtered["stylistic_sets"] = {}

        return filtered

    def _detect_capital_glyphs(self, font: TTFont) -> List[str]:
        """Detect capital letter glyphs from font."""
        glyph_order = set(font.getGlyphOrder())
        best_cmap = font.getBestCmap() or {}

        capitals = []
        # Find uppercase letters using Unicode mapping
        for cp in range(0x0041, 0x005B):  # A-Z
            if cp in best_cmap:
                glyph_name = best_cmap[cp]
                if glyph_name in glyph_order:
                    capitals.append(glyph_name)

        return capitals

    def _apply_mode(self, font: TTFont, detected: Dict[str, any]) -> bool:
        """Generate and apply features to the font."""
        if not HAVE_FEALIB:
            cs.StatusIndicator("error").add_message(
                "fontTools.feaLib is required to compile features"
            ).emit()
            return False

        # Ensure GDEF table exists (required for features)
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
            cs.StatusIndicator("created").add_message("Created GDEF table").emit()

        generator = FeatureCodeGenerator()
        ss_manager = StylisticSetManager(font)

        feature_blocks = []
        applied_features = []

        # Check existing features
        existing_features = set()
        has_existing_gsub = False
        has_existing_gpos = False

        if "GSUB" in font:
            gsub = font["GSUB"]
            if hasattr(gsub.table, "FeatureList") and gsub.table.FeatureList:
                for frec in gsub.table.FeatureList.FeatureRecord:
                    existing_features.add(frec.FeatureTag)
                if len(existing_features) > 0:
                    has_existing_gsub = True

        if "GPOS" in font:
            gpos = font["GPOS"]
            if hasattr(gpos.table, "FeatureList") and gpos.table.FeatureList:
                if len(gpos.table.FeatureList.FeatureRecord) > 0:
                    has_existing_gpos = True

        # If preserving and we have existing features, extract them as FEA using fontFeatures
        existing_fea_code = ""
        existing_ff = None

        if self.preserve_existing and (has_existing_gsub or has_existing_gpos):
            if not HAVE_FONTFEATURES:
                cs.StatusIndicator("error").add_file(
                    self.font_path, filename_only=True
                ).add_message(
                    f"Font has {len(existing_features)} existing feature(s)"
                ).with_explanation(
                    "fontFeatures library is required to preserve existing features. "
                    "Install with: pip install fontFeatures"
                ).emit()
                return False

            try:
                cs.StatusIndicator("info").add_message(
                    f"Extracting {len(existing_features)} existing feature(s) for preservation..."
                ).emit()

                # Extract existing features as FontFeatures object
                existing_ff = fontfeatures_unparse(font, do_gdef=False)

                # Validate existing features
                try:
                    existing_ff.resolveAllRoutines()
                    cs.StatusIndicator("success").add_message(
                        "Validated existing features"
                    ).emit()
                except Exception as e:
                    cs.StatusIndicator("warning").add_message(
                        f"Existing features have validation issues: {e}"
                    ).emit()

                # Convert to FEA code
                existing_fea_code = existing_ff.asFea()

                if existing_fea_code and existing_fea_code.strip():
                    # Filter out 'aalt' feature - it can only contain feature references,
                    # not script statements, and fontFeatures may extract it incorrectly
                    # We'll let the font compiler regenerate it if needed
                    lines = existing_fea_code.split("\n")
                    filtered_lines = []
                    skip_until_close = False
                    brace_count = 0

                    for line in lines:
                        stripped = line.strip()
                        # Check if this is the start of an 'aalt' feature block
                        if stripped.startswith("feature aalt") and "{" in stripped:
                            skip_until_close = True
                            brace_count = stripped.count("{") - stripped.count("}")
                            continue

                        if skip_until_close:
                            brace_count += line.count("{") - line.count("}")
                            # Check if we've closed the feature block
                            if "}" in line and brace_count <= 0:
                                # Skip the closing line too
                                skip_until_close = False
                            continue

                        filtered_lines.append(line)

                    existing_fea_code = "\n".join(filtered_lines).strip()

                    if existing_fea_code:
                        cs.StatusIndicator("success").add_message(
                            "Successfully extracted existing features (aalt filtered)"
                        ).emit()
                    else:
                        cs.StatusIndicator("warning").add_message(
                            "Extracted features but FEA code is empty after filtering"
                        ).emit()
                        existing_fea_code = ""
                else:
                    cs.StatusIndicator("warning").add_message(
                        "Extracted features but FEA code is empty"
                    ).emit()
                    existing_fea_code = ""

            except Exception as e:
                # If extraction fails, abort to be safe
                cs.StatusIndicator("error").add_file(
                    self.font_path, filename_only=True
                ).add_message(
                    f"Failed to extract existing features: {e}"
                ).with_explanation(
                    "Cannot safely add features without preserving existing ones. "
                    "Use --overwrite-features to replace all features."
                ).emit()
                return False

        # If not preserving, warn the user
        if not self.preserve_existing and (has_existing_gsub or has_existing_gpos):
            cs.StatusIndicator("warning").add_message(
                f"OVERWRITE mode: Replacing {len(existing_features)} existing feature(s)"
            ).emit()

        # Extract existing substitutions ONCE at the start using new extractor
        existing_subs = ExistingSubstitutionExtractor(font).extract_all()
        existing_ligature_sequences = existing_subs["ligatures"]
        existing_single_subs = existing_subs["single"]

        # Also extract ligature sequences from the existing FEA code
        # This catches ligatures that exist in FEA but not in GSUB binary tables
        if existing_fea_code and self.preserve_existing:
            fea_only_sequences = set()
            # Parse FEA code for ligature substitutions
            lig_pattern = r"^\s*sub\s+(.+?)\s+by\s+"
            for line in existing_fea_code.split("\n"):
                stripped = line.strip()
                if (
                    stripped.startswith("sub ")
                    and " by " in stripped
                    and stripped.endswith(";")
                ):
                    match = re.match(lig_pattern, line)
                    if match:
                        components_str = match.group(1).strip()
                        normalized = re.sub(r"\s+", " ", components_str)
                        components = tuple(normalized.split(" "))
                        if len(components) >= 2:
                            fea_only_sequences.add(components)

            if fea_only_sequences:
                # Merge FEA sequences with GSUB sequences
                before_count = len(existing_ligature_sequences)
                existing_ligature_sequences.update(fea_only_sequences)
                added_count = len(existing_ligature_sequences) - before_count
                if added_count > 0:
                    cs.StatusIndicator("info").add_message(
                        f"Found {added_count} additional ligature(s) in FEA code not in GSUB"
                    ).emit()

        if existing_ligature_sequences:
            cs.StatusIndicator("info").add_message(
                f"Found {len(existing_ligature_sequences)} existing ligature sequence(s) to preserve"
            ).emit()

        # Filter ALL detected features against existing substitutions early
        filtered_features = self._filter_against_existing(detected, existing_subs)

        # Report what was filtered
        for feature_tag, filtered in filtered_features.items():
            original_count = len(detected.get(feature_tag, []))
            filtered_count = len(filtered)
            if original_count > filtered_count:
                diff = original_count - filtered_count
                cs.StatusIndicator("info").add_message(
                    f"{feature_tag}: Filtered {diff} duplicate(s), keeping {filtered_count}"
                ).emit()

        # Helper to check if feature should be applied
        def should_apply(tag: str) -> bool:
            # Check if explicitly selected
            if self.selected_features and tag not in self.selected_features:
                return False
            return True

        # Use filtered features
        filtered_liga = filtered_features.get("liga", [])

        # Generate ligatures
        if filtered_liga and should_apply("liga"):
            code = generator.generate_liga_feature(filtered_liga)
            if code:
                feature_blocks.append(code)
                # Store glyph details: (tag, count, glyphs_list)
                glyphs = [f"{' '.join(comps)} → {lig}" for comps, lig in filtered_liga]
                applied_features.append(("liga", len(filtered_liga), glyphs))

        # Use filtered discretionary ligatures
        filtered_dlig = filtered_features.get("dlig", [])

        # Generate discretionary ligatures
        if filtered_dlig and should_apply("dlig"):
            code = generator.generate_dlig_feature(filtered_dlig)
            if code:
                feature_blocks.append(code)
                glyphs = [f"{' '.join(comps)} → {lig}" for comps, lig in filtered_dlig]
                applied_features.append(("dlig", len(filtered_dlig), glyphs))

        # Use filtered single substitutions
        # Generate small caps
        if should_apply("smcp"):
            filtered_smcp = filtered_features.get("smcp", [])
            if filtered_smcp:
                code = generator.generate_substitution_feature("smcp", filtered_smcp)
                if code:
                    feature_blocks.append(code)
                    glyphs = [f"{base} → {alt}" for base, alt in filtered_smcp]
                    applied_features.append(("smcp", len(filtered_smcp), glyphs))

        # Generate figure variants
        for tag in ["onum", "lnum", "tnum", "pnum"]:
            if should_apply(tag):
                filtered_subs = filtered_features.get(tag, [])
                if filtered_subs:
                    code = generator.generate_substitution_feature(tag, filtered_subs)
                    if code:
                        feature_blocks.append(code)
                        glyphs = [f"{base} → {alt}" for base, alt in filtered_subs]
                        applied_features.append((tag, len(filtered_subs), glyphs))

        # Generate swashes
        if should_apply("swsh"):
            filtered_swsh = filtered_features.get("swsh", [])
            if filtered_swsh:
                code = generator.generate_substitution_feature("swsh", filtered_swsh)
                if code:
                    feature_blocks.append(code)
                    glyphs = [f"{base} → {alt}" for base, alt in filtered_swsh]
                    applied_features.append(("swsh", len(filtered_swsh), glyphs))

        # Generate contextual alternates
        if should_apply("calt"):
            filtered_calt = filtered_features.get("calt", [])
            if filtered_calt:
                code = generator.generate_substitution_feature("calt", filtered_calt)
                if code:
                    feature_blocks.append(code)
                    glyphs = [f"{base} → {alt}" for base, alt in filtered_calt]
                    applied_features.append(("calt", len(filtered_calt), glyphs))

        # Phase 1 enhanced features
        # Generate fractions (skip if enhanced positioning will be used)
        use_enhanced_frac = self.enable_positioning and (
            filtered_features.get("numr") or filtered_features.get("dnom")
        )

        if should_apply("frac") and not use_enhanced_frac:
            frac_data = filtered_features.get("frac", {})
            if isinstance(frac_data, dict):
                numerators = frac_data.get("numerators", [])
                denominators = frac_data.get("denominators", [])
            else:
                # Handle legacy format
                numerators = []
                denominators = []
            if numerators or denominators:
                code = generator.generate_frac_feature(numerators, denominators, font)
                if code:
                    feature_blocks.append(code)
                    glyphs = []
                    for base, variant in numerators:
                        glyphs.append(f"{base} → {variant} (numerator)")
                    for base, variant in denominators:
                        glyphs.append(f"{base} → {variant} (denominator)")
                    applied_features.append(
                        ("frac", len(numerators) + len(denominators), glyphs)
                    )

        # Generate superscripts
        if should_apply("sups"):
            filtered_sups = filtered_features.get("sups", [])
            if filtered_sups:
                code = generator.generate_sups_feature(filtered_sups)
                if code:
                    feature_blocks.append(code)
                    glyphs = [f"{base} → {alt}" for base, alt in filtered_sups]
                    applied_features.append(("sups", len(filtered_sups), glyphs))

        # Generate subscripts
        if should_apply("subs"):
            filtered_subs = filtered_features.get("subs", [])
            if filtered_subs:
                code = generator.generate_subs_feature(filtered_subs)
                if code:
                    feature_blocks.append(code)
                    glyphs = [f"{base} → {alt}" for base, alt in filtered_subs]
                    applied_features.append(("subs", len(filtered_subs), glyphs))

        # Generate ordinals
        if should_apply("ordn"):
            filtered_ordn = filtered_features.get("ordn", [])
            if filtered_ordn:
                code = generator.generate_ordn_feature(filtered_ordn, font)
                if code:
                    feature_blocks.append(code)
                    glyphs = [f"{base} → {alt}" for base, alt in filtered_ordn]
                    applied_features.append(("ordn", len(filtered_ordn), glyphs))

        # Generate caps to small caps
        if should_apply("c2sc"):
            filtered_c2sc = filtered_features.get("c2sc", [])
            if filtered_c2sc:
                code = generator.generate_c2sc_feature(filtered_c2sc)
                if code:
                    feature_blocks.append(code)
                    glyphs = [f"{base} → {alt}" for base, alt in filtered_c2sc]
                    applied_features.append(("c2sc", len(filtered_c2sc), glyphs))

        # Generate stylistic alternates (salt)
        if should_apply("salt"):
            filtered_salt = filtered_features.get("salt", [])
            if filtered_salt:
                code = generator.generate_salt_feature(filtered_salt)
                if code:
                    feature_blocks.append(code)
                    glyphs = [f"{base} → {alt}" for base, alt in filtered_salt]
                    applied_features.append(("salt", len(filtered_salt), glyphs))

        # Generate slashed zero
        if should_apply("zero"):
            filtered_zero = filtered_features.get("zero", [])
            if filtered_zero:
                code = generator.generate_zero_feature(filtered_zero)
                if code:
                    feature_blocks.append(code)
                    glyphs = [f"{base} → {alt}" for base, alt in filtered_zero]
                    applied_features.append(("zero", len(filtered_zero), glyphs))

        # Generate case-sensitive forms
        if should_apply("case"):
            filtered_case = filtered_features.get("case", [])
            if filtered_case:
                code = generator.generate_case_feature(filtered_case, font)
                if code:
                    feature_blocks.append(code)
                    glyphs = [f"{base} → {alt}" for base, alt in filtered_case]
                    applied_features.append(("case", len(filtered_case), glyphs))

        # Generate titling alternates
        if should_apply("titl"):
            filtered_titl = filtered_features.get("titl", [])
            if filtered_titl:
                code = generator.generate_titl_feature(filtered_titl)
                if code:
                    feature_blocks.append(code)
                    glyphs = [f"{base} → {alt}" for base, alt in filtered_titl]
                    applied_features.append(("titl", len(filtered_titl), glyphs))

        # Phase 2 positioning features
        from opentype_features.opentype_features_positioning import (
            PositioningRuleGenerator,
        )

        # Generate numr, dnom, sinf, hist features (simple substitutions)
        for tag in ["numr", "dnom", "sinf", "hist"]:
            if should_apply(tag):
                filtered_subs = filtered_features.get(tag, [])
                if filtered_subs:
                    code = generator.generate_substitution_feature(tag, filtered_subs)
                    if code:
                        feature_blocks.append(code)
                        glyphs = [f"{base} → {alt}" for base, alt in filtered_subs]
                        applied_features.append((tag, len(filtered_subs), glyphs))

        # Capital spacing (cpsp) - requires positioning enabled
        if should_apply("cpsp") and self.enable_positioning:
            pos_gen = PositioningRuleGenerator(font)
            capital_glyphs = self._detect_capital_glyphs(font)
            if capital_glyphs:
                cpsp_code = pos_gen.generate_cpsp_rules(capital_glyphs)
                if cpsp_code:
                    feature_blocks.append(cpsp_code)
                    applied_features.append(("cpsp", len(capital_glyphs), []))

        # Enhanced fraction positioning (if numr/dnom exist and positioning enabled)
        if should_apply("frac") and self.enable_positioning:
            frac_data = filtered_features.get("frac", {})
            numr_data = filtered_features.get("numr", [])
            dnom_data = filtered_features.get("dnom", [])

            # Use enhanced positioning if numr/dnom exist
            if numr_data or dnom_data:
                pos_gen = PositioningRuleGenerator(font)
                numr_glyphs = [g for _, g in numr_data] if numr_data else []
                dnom_glyphs = [g for _, g in dnom_data] if dnom_data else []
                frac_code = pos_gen.generate_fraction_positioning(
                    numr_glyphs, dnom_glyphs
                )
                if frac_code:
                    # Check if we already added a simple frac feature
                    # If so, we should replace it, but for now just add the enhanced one
                    # (The simple one will be filtered out by the compiler)
                    feature_blocks.append(frac_code)
                    applied_features.append(
                        ("frac", len(numr_glyphs) + len(dnom_glyphs), [])
                    )

        # Kern audit and repair (automatic when positioning enabled)
        if self.enable_positioning:
            pos_gen = PositioningRuleGenerator(font)
            kern_issues = pos_gen.validate_kern_table(font)

            if kern_issues.get("missing_pairs") or kern_issues.get("extreme_values"):
                cs.StatusIndicator("info").add_message(
                    f"Kerning audit: {len(kern_issues.get('missing_pairs', []))} missing pairs, "
                    f"{len(kern_issues.get('extreme_values', []))} extreme values"
                ).emit()

                if self.apply_kern_repair and kern_issues.get("missing_pairs"):
                    kern_repair_code = pos_gen.repair_kern_table(kern_issues)
                    if kern_repair_code:
                        feature_blocks.append(kern_repair_code)
                        applied_features.append(
                            ("kern", len(kern_issues["missing_pairs"]), [])
                        )

        # Generate stylistic sets (filtered at substitution level)
        if detected["stylistic_sets"]:
            processed_sets = ss_manager.process_stylistic_sets(
                detected["stylistic_sets"], self.ss_labels
            )

            for ss_num, (substitutions, name_id, label) in processed_sets.items():
                ss_tag = f"ss{ss_num:02d}"

                # Check selection (handle ranges like ss01-ss05)
                if self.selected_features:
                    # Check for explicit tag
                    if ss_tag not in self.selected_features:
                        # Check for range patterns
                        in_range = False
                        for sel in self.selected_features:
                            if "-" in sel and sel.startswith("ss"):
                                try:
                                    start, end = sel.split("-")
                                    start_num = int(start[2:])
                                    end_num = int(end[2:])
                                    if start_num <= ss_num <= end_num:
                                        in_range = True
                                        break
                                except ValueError:
                                    pass
                        if not in_range:
                            continue

                if should_apply(ss_tag):
                    # Filter stylistic set substitutions against existing
                    filtered_ss_subs = [
                        (base, alt)
                        for base, alt in substitutions
                        if (base, alt) not in existing_single_subs
                    ]
                    if not filtered_ss_subs:
                        continue
                    code = generator.generate_stylistic_set_feature(
                        ss_num, filtered_ss_subs
                    )
                    if code:
                        feature_blocks.append(code)
                        # Store name_id, label, and glyph details for display
                        glyphs = [f"{base} → {alt}" for base, alt in filtered_ss_subs]
                        applied_features.append(
                            (ss_tag, len(filtered_ss_subs), name_id, label, glyphs)
                        )

        if not feature_blocks:
            cs.StatusIndicator("info").add_file(
                self.font_path, filename_only=True
            ).add_message("No features to apply").emit()
            return True

        # Compile all features
        new_features_fea = "\n\n".join(feature_blocks)

        # Combine with existing features if we extracted them
        if existing_fea_code:
            # Don't deduplicate FEA code - it breaks lookup references in contextual rules
            # We're already handling duplicates at the GSUB/detection level

            # Put existing features first, then new ones
            combined_fea = existing_fea_code + "\n\n" + new_features_fea
            cs.StatusIndicator("info").add_message(
                "Merging new features with existing features"
            ).emit()
        else:
            combined_fea = new_features_fea

        if self.dry_run:
            cs.StatusIndicator("preview", dry_run=True).add_file(
                self.font_path, filename_only=True
            ).add_message("Would apply features:").emit()
        else:
            cs.StatusIndicator("info").add_file(
                self.font_path, filename_only=True
            ).add_message("Applying features...").emit()

        # Report what's being applied
        for item in applied_features:
            if len(item) == 5:  # Stylistic set with label and glyphs
                tag, count, name_id, label, glyphs = item
                cs.emit(f"{cs.indent(1)}✓ {tag}: {count} substitutions ({label})")
                # Show first 3 glyphs
                for glyph in glyphs[:3]:
                    cs.emit(f"{cs.indent(2)}{glyph}")
                if len(glyphs) > 3:
                    cs.emit(f"{cs.indent(2)}... and {len(glyphs) - 3} more")
            elif len(item) == 3:  # Regular feature with glyphs
                tag, count, glyphs = item
                cs.emit(f"{cs.indent(1)}✓ {tag}: {count} substitutions")
                # Show first 3 glyphs
                for glyph in glyphs[:3]:
                    cs.emit(f"{cs.indent(2)}{glyph}")
                if len(glyphs) > 3:
                    cs.emit(f"{cs.indent(2)}... and {len(glyphs) - 3} more")
            else:  # Legacy format (shouldn't happen)
                tag, count = item[:2]
                cs.emit(f"{cs.indent(1)}✓ {tag}: {count} substitutions")

        if self.dry_run:
            return True

        # Compile and add to font
        try:
            # Add features (rebuilds GSUB/GPOS tables with merged features)
            # combined_fea already contains merged features if existing_fea_code was found
            addOpenTypeFeaturesFromString(font, combined_fea)

            # Sort Coverage tables after compilation
            try:
                sort_coverage_tables_in_font(font, verbose=False)
            except Exception as e:
                cs.StatusIndicator("warning").add_message(
                    f"Failed to sort Coverage tables: {e}"
                ).with_explanation("Continuing without sorting").emit()

            # Optimize features if requested
            if self.optimize and HAVE_FONTFEATURES and Optimizer:
                try:
                    cs.StatusIndicator("info").add_message(
                        "Optimizing features (deduplicating lookups, merging rules)..."
                    ).emit()

                    # Extract the newly compiled features
                    optimized_ff = fontfeatures_unparse(font, do_gdef=False)

                    # Optimize
                    optimizer = Optimizer(optimized_ff)
                    optimizer.optimize(level=1)  # Level 1 is safe, conservative

                    # Convert back to FEA and recompile
                    optimized_fea = optimized_ff.asFea()
                    addOpenTypeFeaturesFromString(font, optimized_fea)

                    # Sort Coverage tables after optimization recompilation
                    try:
                        sort_coverage_tables_in_font(font, verbose=False)
                    except Exception as e:
                        cs.StatusIndicator("warning").add_message(
                            f"Failed to sort Coverage tables after optimization: {e}"
                        ).with_explanation("Continuing without sorting").emit()

                    cs.StatusIndicator("success").add_message(
                        "Features optimized successfully"
                    ).emit()

                except Exception as e:
                    cs.StatusIndicator("warning").add_message(
                        f"Optimization failed: {e}"
                    ).with_explanation("Continuing with unoptimized features").emit()

            # Set FeatureParams for stylistic sets with UINameID
            if "GSUB" in font:
                gsub = font["GSUB"]
                if hasattr(gsub.table, "FeatureList") and gsub.table.FeatureList:
                    for item in applied_features:
                        if len(item) == 4:  # Stylistic set with name_id and label
                            ss_tag, count, name_id, label = item
                            # Find the feature record
                            for frec in gsub.table.FeatureList.FeatureRecord:
                                if frec.FeatureTag == ss_tag:
                                    # Create or update FeatureParams
                                    if (
                                        not hasattr(frec.Feature, "FeatureParams")
                                        or frec.Feature.FeatureParams is None
                                    ):
                                        params = otTables.FeatureParamsStylisticSet()
                                        params.Version = 0
                                        frec.Feature.FeatureParams = params
                                    frec.Feature.FeatureParams.UINameID = name_id
                                    # Ensure name table entry exists
                                    ss_manager.add_name_record(name_id, label)
                                    break

            # Create backup of original font
            backup_path = self._build_backup_path()
            try:
                shutil.copy2(self.font_path, backup_path)
                cs.StatusIndicator("created").add_message(
                    f"Backup: {os.path.basename(backup_path)}"
                ).emit()
            except Exception as e:
                cs.StatusIndicator("warning").add_message(
                    f"Could not create backup: {e}"
                ).emit()

            # Save modified font with original name
            out_path = self._build_output_path()
            font.save(out_path)

            cs.StatusIndicator("saved").add_file(out_path, filename_only=False).emit()

            return True

        except Exception as e:
            # Write FEA to temp file for debugging
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".fea", delete=False
            ) as f:
                f.write(combined_fea)
                temp_fea_path = f.name

            cs.StatusIndicator("error").add_message(
                f"Failed to compile features: {e}"
            ).with_explanation(f"Combined FEA code saved to: {temp_fea_path}").emit()
            return False

    def _build_output_path(self) -> str:
        """Build output file path (keeps original name)."""
        return self.font_path

    def _build_backup_path(self) -> str:
        """Build backup file path."""
        root, ext = os.path.splitext(self.font_path)
        return f"{root}~backup{ext}"


# ============================================================================
# CLI & MAIN
# ============================================================================


def parse_feature_selection(features_str: str) -> Set[str]:
    """
    Parse feature selection string.
    Examples: "liga,smcp,ss01-ss05"
    """
    selected = set()

    for part in features_str.split(","):
        part = part.strip()
        if "-" in part and part.startswith("ss"):
            # Range like ss01-ss05
            selected.add(part)
            try:
                start, end = part.split("-")
                start_num = int(start[2:])
                end_num = int(end[2:])
                for num in range(start_num, end_num + 1):
                    selected.add(f"ss{num:02d}")
            except (ValueError, IndexError):
                pass
        else:
            selected.add(part)

    return selected


def main():
    # Check if first non-flag arg is "wrapper" subcommand
    # Skip past flags to find first positional argument
    first_pos_arg = None
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            first_pos_arg = arg
            break

    is_wrapper_command = first_pos_arg == "wrapper"

    parser = argparse.ArgumentParser(
        description="Unified OpenType feature tool: detect/generate features, audit/repair existing sets, or add table scaffolding",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze font (show detected features)
  %(prog)s font.otf
  
  # Apply all detected features
  %(prog)s font.otf --apply
  
  # Apply with custom stylistic set labels
  %(prog)s font.otf --apply -ss "14,Diamond Bullets" -ss "1,Swash Capitals"
  
  # Audit existing stylistic sets
  %(prog)s font.otf --audit
  
  # Repair existing stylistic sets
  %(prog)s font.otf --audit --apply -ss "14,Diamond Bullets"
  
  # Add table scaffolding (wrapper subcommand)
  %(prog)s wrapper font.otf --enrich --drop-kern
        """,
    )

    # Only add subparsers if we detected wrapper command
    # This prevents argparse from trying to match font paths as subcommands
    if is_wrapper_command:
        subparsers = parser.add_subparsers(
            dest="command", help="Command to run", required=True
        )
    else:
        # For main command, don't use subparsers to avoid conflicts
        subparsers = None

    # Main command parser (default)
    main_parser = parser
    if not is_wrapper_command:
        main_parser.add_argument(
            "fonts", nargs="+", help="Font file(s) or glob patterns to process"
        )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply detected features to fonts (default: analyze only)",
    )

    parser.add_argument(
        "-fea",
        "--features",
        type=str,
        help="Comma-separated list of features to apply (e.g., liga,smcp,ss01-ss05)",
    )

    parser.add_argument(
        "-ss",
        "--stylistic-set-labels",
        action="append",
        dest="ss_labels",
        metavar="NUM,LABEL,...",
        help='Stylistic set labels: -ss "1,Label" or -ss "1,Label,2,Label". Can be used multiple times.',
    )

    parser.add_argument(
        "--overwrite-features",
        action="store_true",
        dest="overwrite_features",
        help="Overwrite existing features instead of preserving them (feature generation mode)",
    )

    parser.add_argument(
        "-r", "--recursive", action="store_true", help="Recursively process directories"
    )

    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be done without modifying files",
    )

    parser.add_argument(
        "--optimize",
        action="store_true",
        help="Optimize features after compilation (deduplicate lookups, merge rules)",
    )

    parser.add_argument(
        "--skip-validation",
        action="store_true",
        dest="skip_validation",
        help="Skip validation warnings and proceed anyway (wrapper mode only, USE WITH CAUTION)",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed validation results",
    )

    parser.add_argument(
        "-cs",
        "--coverage-sort",
        action="store_true",
        dest="coverage_sort",
        help="Sort GSUB/GPOS Coverage tables by glyph ID (can be used standalone or with other operations)",
    )

    parser.add_argument(
        "--audit",
        action="store_true",
        help="Audit existing stylistic sets (check FeatureParams, UINameIDs, labels)",
    )

    parser.add_argument(
        "--add-missing-params",
        action="store_true",
        dest="add_missing_params",
        help="When used with --audit --apply, create missing FeatureParams",
    )

    parser.add_argument(
        "--overwrite-labels",
        action="store_true",
        dest="overwrite_labels",
        help="Overwrite existing name table labels when used with --audit --apply (audit/repair mode)",
    )

    parser.add_argument(
        "--enable-positioning",
        action="store_true",
        dest="enable_positioning",
        help="Enable Phase 2 positioning features (cpsp, enhanced frac, kern repair)",
    )

    parser.add_argument(
        "--apply-kern-repair",
        action="store_true",
        dest="apply_kern_repair",
        help="Automatically repair missing kerning pairs (requires --enable-positioning)",
    )

    # Wrapper subcommand (only create if subparsers exist)
    wrapper_parser = None
    if subparsers:
        wrapper_parser = subparsers.add_parser(
            "wrapper",
            help="Add OpenType table scaffolding (cmap/GDEF/GPOS/GSUB)",
            description="Add minimal OpenType layout tables to fonts without format conversion",
        )
    if wrapper_parser:
        wrapper_parser.add_argument(
            "fonts", nargs="+", help="Font file(s) or glob patterns to process"
        )
        wrapper_parser.add_argument(
            "--overwrite-cmap",
            action="store_true",
            help="Rebuild Unicode cmap from glyph names",
        )
        wrapper_parser.add_argument(
            "--overwrite-gdef",
            action="store_true",
            help="Replace existing GDEF with empty table",
        )
        wrapper_parser.add_argument(
            "--overwrite-gpos",
            action="store_true",
            help="Replace existing GPOS with empty table",
        )
        wrapper_parser.add_argument(
            "--overwrite-gsub",
            action="store_true",
            help="Replace existing GSUB with empty table",
        )
        wrapper_parser.add_argument(
            "--enrich",
            action="store_true",
            default=True,
            help="Infer and add real OT data: migrate kern table, add liga, build GDEF classes (default: enabled)",
        )
        wrapper_parser.add_argument(
            "--no-enrich",
            action="store_false",
            dest="enrich",
            help="Disable enrichment (only add table scaffolding)",
        )
        wrapper_parser.add_argument(
            "--no-kern-migration",
            action="store_true",
            dest="enrich_no_kern_migration",
            help="When --enrich, skip migrating kern to GPOS",
        )
        wrapper_parser.add_argument(
            "--no-liga",
            action="store_true",
            dest="enrich_no_liga",
            help="When --enrich, skip inferring liga from names",
        )
        wrapper_parser.add_argument(
            "--no-gdef-classes",
            action="store_true",
            dest="enrich_no_gdef_classes",
            help="When --enrich, skip building GDEF glyph classes",
        )
        wrapper_parser.add_argument(
            "--no-lig-carets",
            action="store_true",
            dest="enrich_no_lig_carets",
            help="When --enrich, skip adding ligature carets",
        )
        wrapper_parser.add_argument(
            "--drop-kern",
            action="store_true",
            help="After successful kern migration to GPOS, drop legacy 'kern' table",
        )
        wrapper_parser.add_argument(
            "--no-dsig",
            action="store_true",
            dest="no_dsig",
            help="Don't add DSIG stub (default is to add if missing)",
        )
        wrapper_parser.add_argument(
            "-r",
            "--recursive",
            action="store_true",
            help="Recursively process directories",
        )
        wrapper_parser.add_argument(
            "--coverage-sort",
            action="store_true",
            dest="coverage_sort",
            help="Sort GSUB/GPOS Coverage tables by glyph ID",
        )

    args = parser.parse_args()

    # Set command if we detected wrapper, or ensure it exists
    if is_wrapper_command:
        args.command = "wrapper"
    elif not hasattr(args, "command"):
        args.command = None

    # Parse SS labels early (used by both main and audit modes)
    ss_labels = None
    if hasattr(args, "ss_labels") and args.ss_labels:
        ss_labels = {}

        # Combine all -ss arguments
        all_parts = []
        for ss_arg in args.ss_labels:
            parts = [p.strip() for p in ss_arg.split(",")]
            all_parts.extend(parts)

        if len(all_parts) % 2 != 0:
            cs.StatusIndicator("error").add_message(
                "Invalid -ss format: must have pairs of number,label"
            ).with_explanation(
                'Example: -ss "1,Swash Capitals" or -ss "1,Label,2,Label"'
            ).emit()
            return 1

        try:
            for i in range(0, len(all_parts), 2):
                ss_num = int(all_parts[i])
                label = all_parts[i + 1]

                if not (1 <= ss_num <= 20):
                    cs.StatusIndicator("error").add_message(
                        f"Invalid stylistic set number: {ss_num}"
                    ).with_explanation("Stylistic sets must be between 1 and 20").emit()
                    return 1

                ss_labels[ss_num] = label
                cs.StatusIndicator("info").add_message(
                    f'Label: ss{ss_num:02d} = "{label}"'
                ).emit()

        except (ValueError, IndexError) as e:
            cs.StatusIndicator("error").add_message(
                "Failed to parse -ss labels"
            ).with_explanation(f"Error: {e}").emit()
            return 1

    # Handle wrapper subcommand
    if args.command == "wrapper":
        font_files = core_collect_font_files(
            args.fonts,
            recursive=args.recursive,
            allowed_extensions=SUPPORTED_EXTENSIONS,
        )

        if not font_files:
            cs.StatusIndicator("error").add_message(
                "No font files found matching the patterns"
            ).emit()
            return 1

        cs.StatusIndicator("info").add_message(
            f"Processing {len(font_files)} font(s) with wrapper..."
        ).emit()
        cs.emit("")

        success_count = 0
        error_count = 0

        for font_path in font_files:
            # Show file being processed
            cs.StatusIndicator("parsing").add_file(font_path, filename_only=True).emit()

            # Build user preferences dict
            # Default enrich to True if not explicitly set
            enrich_value = getattr(args, "enrich", True)
            user_prefs = {
                "overwrite_cmap": args.overwrite_cmap,
                "overwrite_gdef": args.overwrite_gdef,
                "overwrite_gsub": args.overwrite_gsub,
                "overwrite_gpos": args.overwrite_gpos,
                "enrich": enrich_value,
                "enrich_no_kern_migration": args.enrich_no_kern_migration,
                "enrich_no_liga": args.enrich_no_liga,
                "enrich_no_gdef_classes": args.enrich_no_gdef_classes,
                "enrich_no_lig_carets": args.enrich_no_lig_carets,
                "drop_kern": args.drop_kern,
                "add_dsig": not args.no_dsig,
                "force": getattr(args, "skip_validation", False),
            }

            result = process_wrapper_font_v2(
                font_path,
                user_prefs,
                dry_run=getattr(args, "dry_run", False),
            )

            # Handle --coverage-sort if requested (even if no other changes)
            # This runs after wrapper operations, so we need to open the font again
            if getattr(args, "coverage_sort", False) and not getattr(
                args, "dry_run", False
            ):
                try:
                    font = TTFont(font_path)
                    total, sorted_count = sort_coverage_tables_in_font(
                        font, verbose=getattr(args, "verbose", False)
                    )
                    if sorted_count > 0:
                        font.save(font_path)
                        result.add_info(
                            f"Sorted {sorted_count} of {total} Coverage table(s)"
                        )
                    elif total > 0:
                        result.add_info(f"All {total} Coverage table(s) already sorted")
                    font.close()
                except Exception as e:
                    result.add_error(
                        f"Failed to sort Coverage tables: {e}",
                        "Coverage sorting failed",
                    )

            # Always show what was done (filter out info messages in non-verbose mode)
            verbose = getattr(args, "verbose", False)
            if verbose:
                result.emit_all()
            else:
                # Show only important messages (info for operations, warnings, errors)
                for msg in result.messages:
                    if msg.level.value in ("info", "error", "critical", "warning"):
                        # Map result levels to status indicator types
                        status_map = {
                            "info": "info",
                            "error": "error",
                            "critical": "error",
                            "warning": "warning",
                        }
                        indicator = cs.StatusIndicator(
                            status_map.get(msg.level.value, "info")
                        )
                        indicator.add_message(msg.message)
                        if msg.details:
                            indicator.with_explanation(msg.details)
                        indicator.emit()

            # Stop if validation failed and not forcing
            if not result.success and not user_prefs.get("force", False):
                cs.StatusIndicator("error").add_message(
                    "Stopped due to validation errors"
                ).with_explanation(
                    "Review issues above. Use --skip-validation to proceed anyway (not recommended)."
                ).emit()
                error_count += 1
                continue

            if result.success:
                # Check if file was actually saved (indicates changes were made)
                was_saved = any("Saved:" in str(msg.message) for msg in result.messages)

                if was_saved:
                    success_count += 1
                    # Show summary of what was done
                    changes_summary = []
                    saved_message = None
                    for msg in result.messages:
                        msg_str = str(msg.message)
                        if "Saved:" in msg_str:
                            saved_message = msg_str
                        elif (
                            "Created" in msg_str
                            or "Migrate" in msg_str
                            or "Enrich" in msg_str
                        ):
                            changes_summary.append(msg_str)

                    # Show saved status
                    if saved_message:
                        cs.StatusIndicator("saved").add_file(
                            font_path, filename_only=False
                        ).emit()
                    # Show what was done
                    if changes_summary:
                        cs.StatusIndicator("updated").add_file(
                            font_path, filename_only=True
                        ).with_explanation("; ".join(changes_summary[:3])).emit()
                else:
                    # No changes needed
                    cs.StatusIndicator("unchanged").add_file(
                        font_path, filename_only=True
                    ).emit()
            else:
                error_count += 1

        cs.emit("")
        cs.StatusIndicator("info").add_message(
            f"Processed: {success_count} updated, {len(font_files) - success_count - error_count} unchanged, {error_count} errors"
        ).emit()

        return 0 if error_count == 0 else 1

    # Handle audit/repair mode
    if args.audit:
        if not args.fonts:
            cs.StatusIndicator("error").add_message("No font files specified").emit()
            return 1

        font_files = core_collect_font_files(
            args.fonts,
            recursive=args.recursive
            if hasattr(args, "recursive") and args.recursive
            else False,
            allowed_extensions=SUPPORTED_EXTENSIONS,
        )

        if not font_files:
            cs.StatusIndicator("error").add_message(
                "No font files found matching the patterns"
            ).emit()
            return 1

        cs.StatusIndicator("info").add_message(
            f"Auditing {len(font_files)} font(s)..."
        ).emit()
        cs.emit("")

        success_count = 0
        error_count = 0

        for font_path in font_files:
            report, changed, flagged = audit_and_repair_stylistic_sets(
                font_path=font_path,
                fix=args.apply if hasattr(args, "apply") and args.apply else False,
                add_missing_params=args.add_missing_params
                if hasattr(args, "add_missing_params") and args.add_missing_params
                else False,
                set_labels=ss_labels,
                force_overwrite=getattr(args, "overwrite_labels", False),
                pretend=args.dry_run
                if hasattr(args, "dry_run") and args.dry_run
                else False,
            )

            cs.StatusIndicator("info").add_file(font_path, filename_only=True).emit()
            for line in report:
                if line.startswith("FLAG:"):
                    cs.StatusIndicator("warning").add_message(line).emit()
                elif line.startswith("CREATED ") or line.startswith("UPDATED "):
                    cs.StatusIndicator("updated").add_message(line).emit()
                elif line.startswith("UNCHANGED "):
                    cs.StatusIndicator("unchanged").add_message(line).emit()
                else:
                    cs.emit(line)

            if changed:
                success_count += 1
            elif flagged:
                error_count += 1

        cs.emit("")
        return 0 if error_count == 0 else 1

    # Default: feature generation mode
    if not args.fonts:
        parser.print_help()
        return 1

    # Collect files using core_file_collector
    font_files = core_collect_font_files(
        args.fonts,
        recursive=args.recursive,
        allowed_extensions=SUPPORTED_EXTENSIONS,
    )

    if not font_files:
        cs.StatusIndicator("error").add_message(
            "No font files found matching the patterns"
        ).emit()
        return 1

    # Parse feature selection
    selected_features = None
    if hasattr(args, "features") and args.features:
        selected_features = parse_feature_selection(args.features)

    # Process fonts
    success_count = 0
    error_count = 0

    # Check if we're only doing coverage sorting (standalone mode)
    coverage_sort_only = (
        getattr(args, "coverage_sort", False)
        and not args.apply
        and not args.audit
        and not getattr(args, "command", None)
    )

    if coverage_sort_only:
        cs.StatusIndicator("info").add_message(
            f"Sorting Coverage tables in {len(font_files)} font(s)..."
        ).emit()
        cs.emit("")
    else:
        cs.StatusIndicator("info").add_message(
            f"Processing {len(font_files)} font(s)..."
        ).emit()
        cs.emit("")

    for font_path in font_files:
        # Handle standalone coverage sorting
        if coverage_sort_only:
            try:
                font = TTFont(font_path)
                total, sorted_count = sort_coverage_tables_in_font(
                    font, verbose=args.verbose
                )
                if sorted_count > 0:
                    font.save(font_path)
                    cs.StatusIndicator("updated").add_file(
                        font_path, filename_only=True
                    ).add_message(
                        f"Sorted {sorted_count} of {total} Coverage table(s)"
                    ).emit()
                    success_count += 1
                elif total > 0:
                    cs.StatusIndicator("unchanged").add_file(
                        font_path, filename_only=True
                    ).add_message(
                        f"All {total} Coverage table(s) already sorted"
                    ).emit()
                font.close()
            except Exception as e:
                cs.StatusIndicator("error").add_file(
                    font_path, filename_only=True
                ).with_explanation(f"Failed to sort Coverage tables: {e}").emit()
                error_count += 1
        else:
            processor = FontProcessor(
                font_path=font_path,
                apply_features=args.apply,
                selected_features=selected_features,
                preserve_existing=not getattr(args, "overwrite_features", False),
                ss_labels=ss_labels,
                dry_run=args.dry_run,
                optimize=args.optimize,
                enable_positioning=getattr(args, "enable_positioning", False),
                apply_kern_repair=getattr(args, "apply_kern_repair", False),
            )

            if processor.process():
                success_count += 1
            else:
                error_count += 1

            # Handle --coverage-sort if requested (after other operations)
            if getattr(args, "coverage_sort", False) and not args.dry_run:
                try:
                    font = TTFont(font_path)
                    total, sorted_count = sort_coverage_tables_in_font(
                        font, verbose=args.verbose
                    )
                    if sorted_count > 0:
                        font.save(font_path)
                        cs.StatusIndicator("info").add_message(
                            f"Sorted {sorted_count} of {total} Coverage table(s)"
                        ).emit()
                    font.close()
                except Exception as e:
                    cs.StatusIndicator("warning").add_message(
                        f"Failed to sort Coverage tables: {e}"
                    ).with_explanation("Continuing without sorting").emit()

        cs.emit("")

    # Summary
    if len(font_files) > 1:
        cs.StatusIndicator("success").add_message(
            "Processing complete"
        ).with_summary_block(updated=success_count, errors=error_count).emit()

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
