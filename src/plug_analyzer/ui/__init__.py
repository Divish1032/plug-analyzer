"""Public desktop UI boundary.

Controllers should depend on these view models and the ``MainWindow`` signals, not
on individual private widgets.
"""

from plug_analyzer.ui.main_window import MainWindow
from plug_analyzer.ui.view_models import (
    AnalysisResultDisplay,
    AppState,
    ChoiceDisplay,
    MetricDisplay,
    NoticeLevel,
    PlaneSeries,
    PreflightSummary,
    SavedMetricComparisonDisplay,
    SourceSummary,
    StorageSummary,
)

__all__ = [
    "AnalysisResultDisplay",
    "AppState",
    "ChoiceDisplay",
    "MainWindow",
    "MetricDisplay",
    "NoticeLevel",
    "PlaneSeries",
    "PreflightSummary",
    "SavedMetricComparisonDisplay",
    "SourceSummary",
    "StorageSummary",
]
