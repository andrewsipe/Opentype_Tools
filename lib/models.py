"""Data models for OpentypeFlow analysis and batch processing."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class FeatureState(str, Enum):
    ACTIVE = "active"
    PARTIAL = "partial"
    INACTIVE = "inactive"
    ABSENT = "absent"


class ConnectTier(str, Enum):
    SIMPLE = "simple"
    CONTEXTUAL = "contextual"
    LIGATURE = "ligature"


class RecommendTier(str, Enum):
    """How strongly scan suggests wiring a detected feature gap."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    MANUAL = "manual"
    SKIP = "skip"


@dataclass
class FeatureStatus:
    tag: str
    label: str
    state: FeatureState
    connect_tier: ConnectTier
    detected_pairs: List[Tuple[str, str]] = field(default_factory=list)
    wired_pairs: List[Tuple[str, str]] = field(default_factory=list)
    missing_pairs: List[Tuple[str, str]] = field(default_factory=list)
    ligatures: List[Tuple[Tuple[str, ...], str]] = field(default_factory=list)
    missing_ligatures: List[Tuple[Tuple[str, ...], str]] = field(default_factory=list)
    frac_numerators: List[Tuple[str, str]] = field(default_factory=list)
    frac_denominators: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def has_gaps(self) -> bool:
        return self.state in (FeatureState.PARTIAL, FeatureState.INACTIVE)


@dataclass
class WrapStatus:
    needs_scaffolding: bool
    can_wrap: bool
    reason: str = ""
    outline_kind: str = "unknown"
    wrap_plan_summary: str = ""

    @property
    def flagged_unsupported(self) -> bool:
        return self.needs_scaffolding and not self.can_wrap


# Glyph counts below this often indicate trial/subset fonts with little to reconnect.
LIMITED_GLYPH_SET_THRESHOLD = 120


@dataclass(frozen=True)
class InstalledFeatureDetail:
    tag: str
    table: str
    lookup_count: int
    populated: bool
    in_naming_policy: bool

    @property
    def status_label(self) -> str:
        if self.lookup_count == 0:
            return "empty"
        if self.populated:
            return "populated"
        return "lookups only"


@dataclass
class GlyphInventory:
    glyph_count: int
    variant_glyph_count: int
    unicode_mapped_count: int

    @property
    def limited_glyph_set(self) -> bool:
        return self.glyph_count < LIMITED_GLYPH_SET_THRESHOLD

    @property
    def has_variant_glyphs(self) -> bool:
        return self.variant_glyph_count > 0


@dataclass
class FeatureRecommendation:
    tag: str
    label: str
    tier: RecommendTier
    reason: str
    state: FeatureState
    missing_count: int = 0


@dataclass
class FontFeatureAudit:
    path: Path
    existing_tags: set[str]
    gsub_tags: set[str]
    gpos_tags: set[str]
    installed_features: Dict[str, InstalledFeatureDetail]
    features: Dict[str, FeatureStatus]
    stylistic_sets: Dict[str, FeatureStatus]
    wrap_status: WrapStatus
    glyph_inventory: GlyphInventory
    recommendations: List[FeatureRecommendation] = field(default_factory=list)
    otl_stripped_suspected: bool = False
    has_gsub_table: bool = False
    active_fea: str = ""
    warnings: List[str] = field(default_factory=list)

    def gaps(self) -> List[FeatureStatus]:
        out: List[FeatureStatus] = []
        for status in self.features.values():
            if status.has_gaps:
                out.append(status)
        for status in self.stylistic_sets.values():
            if status.has_gaps:
                out.append(status)
        return out


@dataclass
class ConnectOptions:
    include_low: bool = False
    include_manual: bool = False


@dataclass
class ConnectSkippedItem:
    tag: str
    reason: str
    tier: str = ""


@dataclass
class ConnectPlan:
    path: Path
    features: Dict[str, FeatureStatus]
    stylistic_sets: Dict[str, FeatureStatus]
    contextual_tags: List[str] = field(default_factory=list)
    skipped: List[ConnectSkippedItem] = field(default_factory=list)
    blocked: bool = False
    block_reason: str = ""

    @property
    def has_work(self) -> bool:
        return not self.blocked and bool(self.features or self.stylistic_sets)

    def rule_count(self) -> int:
        total = 0
        for status in self.features.values():
            total += len(status.missing_pairs) + len(status.missing_ligatures)
        for status in self.stylistic_sets.values():
            total += len(status.missing_pairs)
        return total


@dataclass
class FontProcessResult:
    path: Path
    audit: Optional[FontFeatureAudit] = None
    skipped: bool = False
    error: Optional[str] = None
    saved: bool = False


@dataclass
class BatchSummary:
    fonts_processed: int = 0
    fonts_updated: int = 0
    fonts_skipped: int = 0
    fonts_errors: int = 0
    wrap_flagged: List[str] = field(default_factory=list)
