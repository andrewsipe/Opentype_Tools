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

    # Phase 1 feature patterns
    PHASE1_FEATURE_PATTERNS: Dict[str, List[str]] = field(
        default_factory=lambda: {
            "frac": [".numerator", ".denominator", ".numr", ".dnom"],
            "sups": [".superior", ".sups"],
            "subs": [".inferior", ".subs"],
            "ordn": [".ordn"],
            "c2sc": [".c2sc"],
            "salt": [".alt", ".alt01", ".alt02"],
            "zero": [".slash", ".zero"],
            "case": [".case"],
            "titl": [".titling", ".titl"],
        }
    )

    # Phase 2 feature patterns
    PHASE2_FEATURE_PATTERNS: Dict[str, List[str]] = field(
        default_factory=lambda: {
            "numr": [".numr"],
            "dnom": [".dnom"],
            "sinf": [".sinf"],
            "hist": [".hist"],
        }
    )

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


# Global configuration instance
CONFIG = FeatureConfig()
