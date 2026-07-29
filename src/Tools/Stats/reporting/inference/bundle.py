"""Report bundle contracts and stable reporting constants."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


REPORT_SCHEMA_VERSION = 2
METHOD_DEPENDENT_PHRASE = "Results are method-dependent."
ADAPTIVE_HARMONIC_WARNING = (
    "Harmonics were selected adaptively from the same sample. Response-detection "
    "p-values are therefore exploratory post-selection results, not independent "
    "confirmatory tests."
)


def text_frame(text: str) -> pd.DataFrame:
    """Represent a narrative as explicit, ordered workbook rows."""

    lines = str(text).splitlines() or [""]
    return pd.DataFrame(
        [{"line_number": index, "text": line} for index, line in enumerate(lines, 1)]
    )


def unique_frame_name(
    requested: str,
    frames: Mapping[str, pd.DataFrame],
) -> str:
    """Return a deterministic non-colliding frame name."""

    if requested not in frames:
        return requested
    index = 2
    while f"{requested} ({index})" in frames:
        index += 1
    return f"{requested} ({index})"


def report_text_with_export_path(
    text: str,
    export_path: str | Path | None,
) -> str:
    """Update the stable workbook-location line for the actual destination."""

    location = "not yet selected" if export_path is None else str(Path(export_path))
    replacement = f"- Detailed workbook: {location}."
    lines = str(text).splitlines()
    for index, line in enumerate(lines):
        if line.startswith("- Detailed workbook:"):
            lines[index] = replacement
            return "\n".join(lines)
    return "\n".join([*lines, replacement])


@dataclass(frozen=True)
class NativeInferenceReportBundle:
    """Complete GUI-neutral report plus additive workbook-ready source frames."""

    mode: str
    named_frames: Mapping[str, pd.DataFrame]
    test_inventory: pd.DataFrame
    methods: pd.DataFrame
    limitations: pd.DataFrame
    correction_families: pd.DataFrame
    run_summary: pd.DataFrame
    at_a_glance: str
    detailed_methods: str
    export_path: Path | None = None

    def to_frames(
        self,
        *,
        export_path: str | Path | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Return report frames followed by non-destructively preserved sources."""

        actual_path = self.export_path if export_path is None else Path(export_path)
        frames: OrderedDict[str, pd.DataFrame] = OrderedDict(
            [
                (
                    "At a Glance",
                    text_frame(
                        report_text_with_export_path(
                            self.at_a_glance,
                            actual_path,
                        )
                    ),
                ),
                ("Detailed Methods", text_frame(self.detailed_methods)),
                ("Run Summary", self.run_summary.copy()),
                ("Test Inventory", self.test_inventory.copy()),
                ("Methods", self.methods.copy()),
                ("Limitations", self.limitations.copy()),
                ("Correction Families", self.correction_families.copy()),
                (
                    "Export Metadata",
                    pd.DataFrame(
                        [
                            {
                                "report_schema_version": REPORT_SCHEMA_VERSION,
                                "mode": self.mode,
                                "export_path": (
                                    "" if actual_path is None else str(actual_path)
                                ),
                                "workbook_engine": "xlsxwriter",
                                "sheet_name_limit": 31,
                            }
                        ]
                    ),
                ),
            ]
        )
        for name, frame in self.named_frames.items():
            output_name = str(name)
            if output_name in frames:
                output_name = unique_frame_name(f"Source - {output_name}", frames)
            frames[output_name] = frame.copy()
        return dict(frames)


__all__ = [
    "ADAPTIVE_HARMONIC_WARNING",
    "METHOD_DEPENDENT_PHRASE",
    "NativeInferenceReportBundle",
    "REPORT_SCHEMA_VERSION",
]
