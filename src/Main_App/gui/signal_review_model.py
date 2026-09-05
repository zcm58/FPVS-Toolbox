"""Presentation metadata for signal-review items; original evidence stays intact."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SignalReviewItem:
    """Pair a complete workbook row with concise, structured display fields."""

    export_row: tuple[str, ...]
    kind: str
    title: str
    condition: str = ""
    occurrence: str = ""
    channels: str = ""

    def __post_init__(self) -> None:
        if len(self.export_row) not in (4, 7):
            raise ValueError("Signal review rows require four or seven columns.")

    @property
    def participant(self) -> str:
        return self.export_row[0]

    @property
    def recording(self) -> str:
        return self.export_row[1] if len(self.export_row) == 7 else ""

    @property
    def session(self) -> str:
        return self.export_row[2] if len(self.export_row) == 7 else ""

    @property
    def visit(self) -> str:
        return self.export_row[3] if len(self.export_row) == 7 else ""

    @property
    def group(self) -> str:
        return self.export_row[-3]

    @property
    def source_file(self) -> str:
        return self.export_row[-2]

    @property
    def details(self) -> str:
        return self.export_row[-1]

    @property
    def recording_key(self) -> tuple[str, ...]:
        return self.export_row[:-1]

    @property
    def recording_label(self) -> str:
        parts = [self.participant, self.group, self.source_file]
        if self.recording:
            parts.extend((self.recording, f"{self.session} / visit {self.visit}"))
        return " · ".join(parts)

    @property
    def search_text(self) -> str:
        return " ".join(
            (*self.export_row, self.kind, self.title, self.condition,
             self.occurrence, self.channels)
        ).casefold()
