"""Semantic analysis passes for Quest compiler frontend and intermediate representations."""

from quest.analysis.closure import CapturedVar, LambdaAnalysis, analyze_closures, find_free_vars

__all__ = [
    "CapturedVar",
    "LambdaAnalysis",
    "analyze_closures",
    "find_free_vars",
]
