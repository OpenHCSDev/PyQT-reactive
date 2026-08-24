"""Reusable presentation declarations and services."""

from .preview_formatting import (
    FormattingConfig,
    ObjectStatePreviewFormattingService,
    PreviewSegment,
)
from .status_presentation import (
    DefaultStatusPresentationStrategy,
    StatusPresentationInput,
    StatusPresentationResult,
    StatusPresentationStrategyABC,
)
from .tree_aggregation import (
    ExplicitPercentTreeAggregationPolicy,
    MeanTreeAggregationPolicy,
    TreeAggregationPolicyABC,
    TreeAggregationPolicyRegistry,
)

__all__ = [
    "FormattingConfig",
    "ObjectStatePreviewFormattingService",
    "PreviewSegment",
    "StatusPresentationInput",
    "StatusPresentationResult",
    "StatusPresentationStrategyABC",
    "DefaultStatusPresentationStrategy",
    "TreeAggregationPolicyABC",
    "MeanTreeAggregationPolicy",
    "ExplicitPercentTreeAggregationPolicy",
    "TreeAggregationPolicyRegistry",
]
