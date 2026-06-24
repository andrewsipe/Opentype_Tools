"""
Configuration constants for OpenType feature generation.

Centralizes all magic numbers, feature sets, and pattern definitions.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set


@dataclass(frozen=True)
class FeatureConfig:
    """Configuration for feature generation."""

    # Name table
    NAME_ID_START: int = 256
    MAX_STYLISTIC_SETS: int = 20

    # GSUB limits
    MAX_ALTERNATES_PER_SET: int = 50

    # OpenType versions
    OT_VERSION_1_0: int = 0x00010000
    OT_VERSION_1_2: int = 0x00010002

    # Supported features
    STANDARD_FEATURES: Set[str] = frozenset(
        {
            "liga",
            "dlig",
            "smcp",
            "onum",
            "lnum",
            "tnum",
            "pnum",
            "swsh",
            "calt",
            # Phase 1 enhanced features
            "frac",
            "sups",
            "subs",
            "ordn",
            "c2sc",
            "salt",
            "zero",
            "case",
            "titl",
            # Phase 2 positioning features
            "cpsp",
            "numr",
            "dnom",
            "sinf",
            "hist",
            "kern",
        }
    )

    # Phase 1/2 patterns — see lib/feature_policy.py (source of truth)
    PHASE1_FEATURE_PATTERNS: Dict[str, List[str]] = field(default_factory=dict)
    PHASE2_FEATURE_PATTERNS: Dict[str, List[str]] = field(default_factory=dict)

    # Glyph name patterns
    SPECIAL_GLYPHS: Set[str] = frozenset({".notdef", ".null", "nonmarkingreturn"})

    # Mark detection patterns (more precise)
    MARK_PATTERNS: tuple = (
        r".*comb$",  # combining
        r".*comb\d+$",  # combining1, combining2
        r"^comb",  # combdieresis
        r".*mark$",  # topmark, bottommark
        r".*accent$",  # accent
    )


def _build_phase_patterns() -> tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    from .feature_policy import FRAC_FEATURE, SINGLE_FEATURES

    phase1: Dict[str, List[str]] = {
        "frac": list(FRAC_FEATURE.patterns),
    }
    phase2_tags = {"numr", "dnom", "sinf", "hist"}
    phase2: Dict[str, List[str]] = {}
    for entry in SINGLE_FEATURES:
        if not entry.patterns:
            continue
        if entry.tag in phase2_tags:
            phase2[entry.tag] = list(entry.patterns)
        elif entry.tag not in phase1:
            phase1[entry.tag] = list(entry.patterns)
    return phase1, phase2


_p1, _p2 = _build_phase_patterns()


# Global configuration instance
CONFIG = FeatureConfig(
    PHASE1_FEATURE_PATTERNS=_p1,
    PHASE2_FEATURE_PATTERNS=_p2,
)
