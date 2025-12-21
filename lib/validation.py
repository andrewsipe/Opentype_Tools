"""
Validation framework for OpenType feature operations.

Validates font state and proposed operations before execution.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Set

from fontTools.agl import toUnicode
from fontTools.ttLib import TTFont

from .config import CONFIG
from .results import OperationResult


@dataclass
class FontState:
    """Current state of font's OpenType tables."""

    has_cmap: bool = False
    has_unicode_cmap: bool = False
    cmap_entry_count: int = 0

    has_gdef: bool = False
    gdef_has_classes: bool = False
    gdef_has_carets: bool = False

    has_gsub: bool = False
    gsub_lookup_count: int = 0
    gsub_features: Set[str] = field(default_factory=set)

    has_gpos: bool = False
    gpos_lookup_count: int = 0
    gpos_features: Set[str] = field(default_factory=set)

    has_kern: bool = False
    kern_pair_count: int = 0

    has_stat: bool = False
    has_fvar: bool = False

    def is_empty_otl(self) -> bool:
        """Check if OpenType Layout tables are empty."""
        return self.gsub_lookup_count == 0 and self.gpos_lookup_count == 0

    def needs_basic_scaffolding(self) -> bool:
        """Check if basic table scaffolding is needed."""
        return not (self.has_cmap and self.has_gdef and self.has_gsub and self.has_gpos)

    def can_enrich(self) -> bool:
        """Check if font can be enriched (has data to work with)."""
        return self.has_unicode_cmap and self.cmap_entry_count > 0


class FontValidator:
    """Validates font state and proposed operations."""

    def __init__(self, font: TTFont):
        self.font = font
        self.state = self._analyze_font_state()

    def _analyze_font_state(self) -> FontState:
        """Analyze current font state."""
        state = FontState()

        # Check cmap
        if "cmap" in self.font:
            state.has_cmap = True
            try:
                best_cmap = self.font.getBestCmap()
                if best_cmap:
                    state.cmap_entry_count = len(best_cmap)
                    # Check for Windows Unicode specifically
                    for table in self.font["cmap"].tables:
                        if table.platformID == 3 and table.platEncID in (1, 10):
                            if getattr(table, "cmap", None):
                                state.has_unicode_cmap = True
                                break
            except Exception:
                pass

        # Check GDEF
        if "GDEF" in self.font:
            state.has_gdef = True
            gdef = self.font["GDEF"].table
            state.gdef_has_classes = gdef.GlyphClassDef is not None
            state.gdef_has_carets = gdef.LigCaretList is not None

        # Check GSUB
        if "GSUB" in self.font:
            state.has_gsub = True
            gsub = self.font["GSUB"].table
            if hasattr(gsub, "LookupList") and gsub.LookupList:
                state.gsub_lookup_count = len(gsub.LookupList.Lookup)
            if hasattr(gsub, "FeatureList") and gsub.FeatureList:
                state.gsub_features = {
                    frec.FeatureTag for frec in gsub.FeatureList.FeatureRecord
                }

        # Check GPOS
        if "GPOS" in self.font:
            state.has_gpos = True
            gpos = self.font["GPOS"].table
            if hasattr(gpos, "LookupList") and gpos.LookupList:
                state.gpos_lookup_count = len(gpos.LookupList.Lookup)
            if hasattr(gpos, "FeatureList") and gpos.FeatureList:
                state.gpos_features = {
                    frec.FeatureTag for frec in gpos.FeatureList.FeatureRecord
                }

        # Check kern
        if "kern" in self.font:
            state.has_kern = True
            try:
                kern = self.font["kern"]
                subtables = getattr(kern, "kernTables", None) or getattr(
                    kern, "tables", None
                )
                if subtables:
                    for st in subtables:
                        if getattr(st, "format", 0) == 0:
                            table = getattr(st, "kernTable", None)
                            if table:
                                state.kern_pair_count += len(table)
            except Exception:
                pass

        # Check variable font tables
        state.has_stat = "STAT" in self.font
        state.has_fvar = "fvar" in self.font

        return state

    def validate_cmap_operation(self, overwrite: bool) -> OperationResult:
        """Validate cmap creation/modification."""
        result = OperationResult(success=True)

        if not self.state.has_cmap:
            result.add_info("No cmap table found", "Will create from glyph names")
            return result

        if not self.state.has_unicode_cmap:
            result.add_warning(
                "No Unicode cmap found",
                "Existing cmap may be platform-specific (Mac Roman, Symbol, etc.)",
            )
            if not overwrite:
                result.add_info("Will add Unicode cmap alongside existing")
            return result

        if overwrite:
            result.add_warning(
                "Overwriting existing Unicode cmap",
                f"Current cmap has {self.state.cmap_entry_count} entries. "
                "Derived cmap may have different coverage.",
            )
            # Compare coverage
            derived_map = self._derive_unicode_map()
            if len(derived_map) < self.state.cmap_entry_count:
                diff = self.state.cmap_entry_count - len(derived_map)
                result.add_error(
                    f"Would lose {diff} cmap entries",
                    f"Existing: {self.state.cmap_entry_count}, "
                    f"Derived: {len(derived_map)}. "
                    "Consider not using --overwrite-cmap.",
                )
        else:
            result.add_success(
                f"Unicode cmap exists ({self.state.cmap_entry_count} entries)",
                "No changes needed",
            )

        return result

    def validate_otl_operation(
        self, table_name: str, overwrite: bool
    ) -> OperationResult:
        """Validate GDEF/GSUB/GPOS operation."""
        result = OperationResult(success=True)

        state_map = {
            "GDEF": (self.state.has_gdef, None, None),
            "GSUB": (
                self.state.has_gsub,
                self.state.gsub_lookup_count,
                self.state.gsub_features,
            ),
            "GPOS": (
                self.state.has_gpos,
                self.state.gpos_lookup_count,
                self.state.gpos_features,
            ),
        }

        has_table, lookup_count, features = state_map.get(
            table_name, (False, None, None)
        )

        if not has_table:
            result.add_info(f"No {table_name} table found", "Will create empty table")
            return result

        if lookup_count is not None and lookup_count > 0:
            if overwrite:
                feature_list = ", ".join(sorted(features)) if features else "none"
                result.add_warning(
                    f"Overwriting {table_name} with {lookup_count} lookups",
                    f"Features: {feature_list}. All existing data will be lost.",
                )
                result.add_error(
                    f"DESTRUCTIVE: {table_name} has real data",
                    "Consider not using --overwrite flag. "
                    "Use feature generation mode to preserve existing features.",
                )
            else:
                result.add_success(
                    f"{table_name} exists with {lookup_count} lookups",
                    "No changes needed",
                )
        else:
            if overwrite:
                result.add_info(f"{table_name} exists but is empty", "Will replace")
            else:
                result.add_success(f"{table_name} exists (empty)", "No changes needed")

        return result

    def validate_enrichment(self) -> OperationResult:
        """Validate if font can be enriched."""
        result = OperationResult(success=True)

        if not self.state.can_enrich():
            result.add_error(
                "Cannot enrich font",
                f"Font has no usable Unicode cmap "
                f"(has_cmap={self.state.has_cmap}, "
                f"has_unicode={self.state.has_unicode_cmap}, "
                f"entries={self.state.cmap_entry_count})",
            )
            return result

        # Check what can be enriched
        enrichment_opportunities = []

        if self.state.has_kern and self.state.kern_pair_count > 0:
            if "kern" in self.state.gpos_features:
                result.add_info(
                    f"Legacy kern table found ({self.state.kern_pair_count} pairs)",
                    "GPOS kern already exists. Skipping migration to avoid duplicates.",
                )
            else:
                enrichment_opportunities.append(
                    f"Migrate kern table ({self.state.kern_pair_count} pairs) → GPOS"
                )

        # Check for ligature opportunities
        lig_count = len(self._detect_ligature_opportunities())
        if lig_count > 0:
            if "liga" in self.state.gsub_features:
                result.add_info(
                    f"Found {lig_count} potential ligatures",
                    "GSUB liga already exists. Will check for duplicates.",
                )
                enrichment_opportunities.append("Add new ligatures (if not duplicates)")
            else:
                enrichment_opportunities.append(
                    f"Create liga feature ({lig_count} ligatures)"
                )

        # Check for GDEF enrichment
        if not self.state.gdef_has_classes:
            mark_count = len(self._detect_marks())
            if mark_count > 0:
                enrichment_opportunities.append(
                    f"Add GDEF glyph classes ({mark_count} marks detected)"
                )

        if not self.state.gdef_has_carets and lig_count > 0:
            enrichment_opportunities.append(
                f"Add ligature carets ({lig_count} ligatures)"
            )

        if enrichment_opportunities:
            result.add_success(
                f"Font can be enriched ({len(enrichment_opportunities)} opportunities)",
                "\n".join(f"  • {opp}" for opp in enrichment_opportunities),
            )
        else:
            result.add_info(
                "No enrichment opportunities found",
                "Font may already be fully enriched",
            )

        return result

    def _derive_unicode_map(self) -> Dict[int, str]:
        """Helper to derive Unicode map from glyph names."""
        mapping = {}
        for glyph_name in self.font.getGlyphOrder():
            if glyph_name in CONFIG.SPECIAL_GLYPHS:
                continue
            try:
                uni = toUnicode(glyph_name)
                if uni and len(uni) == 1:
                    mapping[ord(uni)] = glyph_name
            except Exception:
                pass
        return mapping

    def _detect_ligature_opportunities(self) -> List[tuple]:
        """Helper to detect potential ligatures."""
        # Simplified version - will be replaced by UnifiedGlyphDetector later
        ligatures = []
        glyph_order = set(self.font.getGlyphOrder())
        best_cmap = self.font.getBestCmap() or {}

        for glyph_name in glyph_order:
            base = glyph_name.split(".")[0]
            components = []

            if "_" in base:
                parts = base.split("_")
            elif len(base) == 2 and all(ch.isalpha() for ch in base):
                parts = [base[0], base[1]]
            else:
                continue

            for part in parts:
                if part.startswith("uni") and len(part) >= 7:
                    hex_part = part[3:7]
                    try:
                        codepoint = int(hex_part, 16)
                        glyph = best_cmap.get(codepoint)
                        if not glyph:
                            components = []
                            break
                        components.append(glyph)
                    except ValueError:
                        components = []
                        break
                else:
                    if part in glyph_order:
                        components.append(part)
                    else:
                        components = []
                        break

            if len(components) >= 2:
                ligatures.append((components, glyph_name))

        return ligatures

    def _detect_marks(self) -> Set[str]:
        """Helper to detect mark glyphs."""
        marks = set()
        inv_cmap = self._invert_cmap()

        # Unicode category check
        for glyph, codepoints in inv_cmap.items():
            for cp in codepoints:
                cat = unicodedata.category(chr(cp))
                if cat in ("Mn", "Mc", "Me"):
                    marks.add(glyph)
                    break

        # Pattern-based detection (more precise now)
        for glyph in self.font.getGlyphOrder():
            lower = glyph.lower()
            for pattern in CONFIG.MARK_PATTERNS:
                if re.match(pattern, lower):
                    marks.add(glyph)
                    break

        return marks

    def _invert_cmap(self) -> Dict[str, List[int]]:
        """Helper to invert cmap."""
        inv = {}
        try:
            best = self.font.getBestCmap() or {}
            for cp, gname in best.items():
                inv.setdefault(gname, []).append(cp)
        except Exception:
            pass
        return inv

