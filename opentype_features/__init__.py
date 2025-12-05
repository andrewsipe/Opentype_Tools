"""
OpenType Features Generator support modules.

This package contains modular components for the OpenType Features Generator tool.
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
    "ExistingSubstitutionExtractor",
    "WrapperPlan",
    "WrapperStrategyEngine",
    "WrapperExecutor",
    "PositioningRuleGenerator",
]

# Import main exports for convenience
from opentype_features.opentype_features_config import CONFIG
from opentype_features.opentype_features_results import (
    OperationResult,
    ResultLevel,
    ResultMessage,
)
from opentype_features.opentype_features_validation import FontValidator, FontState
from opentype_features.opentype_features_detection import (
    UnifiedGlyphDetector,
    GlyphClassification,
)
from opentype_features.opentype_features_extraction import ExistingSubstitutionExtractor
from opentype_features.opentype_features_wrapper import (
    WrapperPlan,
    WrapperStrategyEngine,
    WrapperExecutor,
)
from opentype_features.opentype_features_positioning import PositioningRuleGenerator
