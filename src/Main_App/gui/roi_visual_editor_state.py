"""GUI-neutral ordered collection state for the visual ROI settings editor."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from colorsys import hsv_to_rgb
from dataclasses import dataclass

from Main_App.gui.roi_electrode_selector_state import (
    ROIElectrodeSelectionState,
    split_electrode_text,
)


# These dark categorical accents remain readable beneath white electrode
# labels. They are presentation-only and never enter ROI persistence.
ROI_COLOR_PALETTE: tuple[str, ...] = (
    "#0F6CBD",
    "#8E3B46",
    "#2E7D32",
    "#6B4EA0",
    "#9C5700",
    "#006D77",
    "#8A3D70",
    "#4B5563",
)


def roi_color_for_id(entry_id: int) -> str:
    """Return a deterministic dark accent without cycling the base palette."""

    if entry_id < 1:
        raise ValueError("ROI entry IDs must be positive.")
    if entry_id <= len(ROI_COLOR_PALETTE):
        return ROI_COLOR_PALETTE[entry_id - 1]
    hue = (0.09 + (entry_id - len(ROI_COLOR_PALETTE) - 1) * 0.61803398875) % 1.0
    red, green, blue = hsv_to_rgb(hue, 0.74, 0.48)
    return f"#{round(red * 255):02X}{round(green * 255):02X}{round(blue * 255):02X}"


@dataclass(slots=True)
class ROIEditorEntry:
    """One stable draft row with an independent electrode-selection ledger."""

    entry_id: int
    name: str
    selection: ROIElectrodeSelectionState
    is_default: bool = False

    @property
    def display_name(self) -> str:
        return self.name.strip() or "Untitled ROI"

    def counts(self) -> tuple[int, int]:
        return len(self.selection.selected_electrodes()), len(
            self.selection.selected_map_labels()
        )

    def is_partial(self) -> bool:
        return bool(self.name.strip()) != bool(self.selection.selected_electrodes())


class ROIEditorCollection:
    """Preserve row identity and persistence behavior independently of widgets."""

    def __init__(self, canonical_electrodes: Sequence[str]) -> None:
        self.canonical_electrodes = tuple(canonical_electrodes)
        self.entries: list[ROIEditorEntry] = []
        self._next_entry_id = 1

    def reset(
        self,
        pairs: Iterable[tuple[str, Iterable[str]]],
        *,
        default_pairs: Iterable[tuple[str, Iterable[str]]] = (),
    ) -> None:
        self.entries.clear()
        self._next_entry_id = 1
        saved_pairs = [
            (str(name), self._electrode_values(electrodes))
            for name, electrodes in pairs
        ]
        defaults = [
            (str(name).strip(), self._electrode_values(electrodes))
            for name, electrodes in default_pairs
        ]
        default_keys = {name.casefold() for name, _electrodes in defaults}
        last_saved_default_index = {
            name.strip().casefold(): index
            for index, (name, _electrodes) in enumerate(saved_pairs)
            if name.strip().casefold() in default_keys
        }
        for index, (name, electrodes) in enumerate(saved_pairs):
            name_key = name.strip().casefold()
            is_default = last_saved_default_index.get(name_key) == index
            self._append_entry(name, electrodes, is_default=is_default)

        for default_name, default_electrodes in defaults:
            default_key = default_name.casefold()
            if default_key not in last_saved_default_index:
                self._append_entry(default_name, default_electrodes, is_default=True)
        if not self.entries:
            self.append("", ())

    def append(self, name: str, electrodes: str | Iterable[str]) -> int:
        return self._append_entry(name, electrodes, is_default=False)

    def _append_entry(
        self,
        name: str,
        electrodes: str | Iterable[str],
        *,
        is_default: bool,
    ) -> int:
        values = self._electrode_values(electrodes)
        entry = ROIEditorEntry(
            entry_id=self._next_entry_id,
            name=str(name),
            selection=ROIElectrodeSelectionState(self.canonical_electrodes, values),
            is_default=is_default,
        )
        self._next_entry_id += 1
        self.entries.append(entry)
        return len(self.entries) - 1

    def remove(self, index: int) -> tuple[ROIEditorEntry, int, bool]:
        if self.entries[index].is_default:
            raise ValueError("Default ROIs cannot be removed.")
        removed = self.entries.pop(index)
        appended_blank = False
        if not self.entries:
            self.append("", ())
            appended_blank = True
        return removed, min(index, len(self.entries) - 1), appended_blank

    def get_pairs(self) -> list[tuple[str, list[str]]]:
        pairs: list[tuple[str, list[str]]] = []
        for entry in self.entries:
            name = entry.name.strip()
            electrodes = [label.upper() for label in entry.selection.selected_electrodes()]
            if name and electrodes:
                pairs.append((name, electrodes))
        return pairs

    def first_partial_index(self) -> int | None:
        return next(
            (index for index, entry in enumerate(self.entries) if entry.is_partial()),
            None,
        )

    @staticmethod
    def _electrode_values(electrodes: str | Iterable[str]) -> tuple[str, ...]:
        if isinstance(electrodes, str):
            return split_electrode_text(electrodes)
        return tuple(str(item).strip() for item in electrodes if str(item).strip())


__all__ = [
    "ROIEditorCollection",
    "ROIEditorEntry",
    "ROI_COLOR_PALETTE",
    "roi_color_for_id",
]
