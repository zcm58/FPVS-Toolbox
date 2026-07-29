"""Stable public facade for GUI-neutral native-inference reporting."""

from Tools.Stats.reporting.inference import (
    ADAPTIVE_HARMONIC_WARNING,
    METHOD_DEPENDENT_PHRASE,
    NativeInferenceReportBundle,
    REPORT_SCHEMA_VERSION,
    build_native_inference_report,
    write_native_inference_workbook,
    write_native_numeric_workbook,
)

__all__ = [
    "ADAPTIVE_HARMONIC_WARNING",
    "METHOD_DEPENDENT_PHRASE",
    "NativeInferenceReportBundle",
    "REPORT_SCHEMA_VERSION",
    "build_native_inference_report",
    "write_native_inference_workbook",
    "write_native_numeric_workbook",
]
