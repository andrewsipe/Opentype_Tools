"""
OpenType Tools library modules.

Shared components for OpenType font manipulation tools.
"""

__all__ = [
    "CONFIG",
    "OperationResult",
    "ResultLevel",
    "ResultMessage",
    "FontValidator",
    "FontState",
    "UnifiedGlyphDetector",
    "GlyphClassification",
    "SSLabeler",
    "WrapperPlan",
    "WrapperStrategyEngine",
    "WrapperExecutor",
    "sort_coverage_tables_in_font",
    "FeatureExtractor",
    "ExistingSubstitutionExtractor",
    "FeatureCodeGenerator",
]

# Import main exports for convenience
from lib.config import CONFIG
from lib.results import (
    OperationResult,
    ResultLevel,
    ResultMessage,
)
from lib.validation import FontValidator, FontState
from lib.detection import (
    UnifiedGlyphDetector,
    GlyphClassification,
)
from lib.ss_labeler import SSLabeler
from lib.wrapper import (
    WrapperPlan,
    WrapperStrategyEngine,
    WrapperExecutor,
)
from lib.coverage import sort_coverage_tables_in_font
from lib.feature_extraction import (
    FeatureExtractor,
    ExistingSubstitutionExtractor,
)
from lib.feature_generation import FeatureCodeGenerator
