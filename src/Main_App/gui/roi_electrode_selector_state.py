"""Ordered, GUI-neutral state for the visual ROI electrode selector."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from math import pi, sin, cos


# Electrode-map geometry adapted from zcm58/NERD-Lab-SSSEP-Analysis
# sssep_batch/roi_selection_gui.py at d19d585517d0328eee965935688ba9ba161fd0d0.
# Polar coordinates trace to zcm58.github.io/assets/js/roi-explorer.js at
# 3b797ad45fdecf688a9d82b869a6b7a908f7a555 and BioSemi Cap_coords_all.xls.
BIOSEMI64_POLAR_COORDINATES: tuple[tuple[str, int, int], ...] = (
    ("Fp1", 18, -2),
    ("AF7", 36, -2),
    ("AF3", 25, 16),
    ("F1", 22, 40),
    ("F3", 39, 30),
    ("F5", 49, 15),
    ("F7", 54, -2),
    ("FT7", 72, -2),
    ("FC5", 69, 18),
    ("FC3", 62, 40),
    ("FC1", 45, 58),
    ("C1", 90, 67),
    ("C3", 90, 44),
    ("C5", 90, 21),
    ("T7", 90, -2),
    ("TP7", 108, -2),
    ("CP5", 111, 18),
    ("CP3", 118, 40),
    ("CP1", 135, 58),
    ("P1", 158, 40),
    ("P3", 141, 30),
    ("P5", 131, 15),
    ("P7", 126, -2),
    ("P9", 126, -25),
    ("PO7", 144, -2),
    ("PO3", 155, 16),
    ("O1", 162, -2),
    ("Iz", -180, -25),
    ("Oz", -180, -2),
    ("POz", -180, 21),
    ("Pz", -180, 44),
    ("CPz", -180, 67),
    ("Fpz", 0, -2),
    ("Fp2", -18, -2),
    ("AF8", -36, -2),
    ("AF4", -25, 16),
    ("AFz", 0, 21),
    ("Fz", 0, 44),
    ("F2", -22, 40),
    ("F4", -39, 30),
    ("F6", -49, 15),
    ("F8", -54, -2),
    ("FT8", -72, -2),
    ("FC6", -69, 18),
    ("FC4", -62, 40),
    ("FC2", -45, 58),
    ("FCz", 0, 67),
    ("Cz", -90, 90),
    ("C2", -90, 67),
    ("C4", -90, 44),
    ("C6", -90, 21),
    ("T8", -90, -2),
    ("TP8", -108, -2),
    ("CP6", -111, 18),
    ("CP4", -118, 40),
    ("CP2", -135, 58),
    ("P2", -158, 40),
    ("P4", -141, 30),
    ("P6", -131, 15),
    ("P8", -126, -2),
    ("P10", -126, -25),
    ("PO8", -144, -2),
    ("PO4", -155, 16),
    ("O2", -162, -2),
)

BIOSEMI64_LABELS: tuple[str, ...] = tuple(item[0] for item in BIOSEMI64_POLAR_COORDINATES)


def electrode_logical_position(theta_degrees: int, phi_degrees: int) -> tuple[float, float]:
    """Project a BioSemi polar coordinate onto the selector's logical canvas."""

    radius = 0.5 - phi_degrees / 180
    angle = -theta_degrees * pi / 180
    return (
        320 + 390 * radius * sin(angle),
        300 - 390 * radius * cos(angle),
    )


def split_electrode_text(text: str) -> tuple[str, ...]:
    """Return nonblank comma-separated labels without changing case or order."""

    return tuple(part.strip() for part in str(text).split(",") if part.strip())


class ROIElectrodeSelectionState:
    """Track map membership while preserving the original ordered token ledger."""

    def __init__(
        self,
        canonical_electrodes: Sequence[str],
        current_electrodes: Iterable[str],
    ) -> None:
        canonical = tuple(str(label).strip() for label in canonical_electrodes if str(label).strip())
        keys = tuple(label.casefold() for label in canonical)
        if len(set(keys)) != len(keys):
            raise ValueError("Canonical electrode labels must be unique case-insensitively.")

        self._canonical = canonical
        self._canonical_lookup = dict(zip(keys, canonical))
        self._original = tuple(
            str(label).strip() for label in current_electrodes if str(label).strip()
        )
        self._canonical_counts = Counter(
            label.casefold()
            for label in self._original
            if label.casefold() in self._canonical_lookup
        )
        self._canonical_restore_counts = Counter(self._canonical_counts)
        self._unmapped = tuple(
            label
            for label in self._original
            if label.casefold() not in self._canonical_lookup
        )

    @property
    def canonical_electrodes(self) -> tuple[str, ...]:
        return self._canonical

    @property
    def original_electrodes(self) -> tuple[str, ...]:
        return self._original

    def is_selected(self, label: str) -> bool:
        return self._canonical_counts[str(label).strip().casefold()] > 0

    def set_checked(self, label: str, checked: bool) -> None:
        key = str(label).strip().casefold()
        if key not in self._canonical_lookup:
            raise ValueError(f"Unknown canonical electrode: {label!r}")
        if checked:
            if self._canonical_counts[key] == 0:
                self._canonical_counts[key] = max(
                    1,
                    self._canonical_restore_counts[key],
                )
        else:
            self._canonical_counts.pop(key, None)

    def clear(self) -> None:
        self._canonical_counts.clear()
        self._canonical_restore_counts.clear()
        self._unmapped = ()

    def replace_with(self, electrodes: Iterable[str]) -> tuple[str, ...]:
        """Replace the draft and return preset members that are not on the map."""

        canonical_counts: Counter[str] = Counter()
        unmapped: list[str] = []
        for raw_label in electrodes:
            label = str(raw_label).strip()
            if not label:
                continue
            key = label.casefold()
            if key in self._canonical_lookup:
                canonical_counts[key] += 1
            else:
                unmapped.append(label)
        self._canonical_counts = canonical_counts
        self._canonical_restore_counts = Counter(canonical_counts)
        self._unmapped = tuple(unmapped)
        return self._unmapped

    def set_unmapped(self, electrodes: Iterable[str]) -> tuple[str, ...]:
        """Update fallback labels and return canonical labels promoted to the map."""

        unmapped: list[str] = []
        promoted: list[str] = []
        for raw_label in electrodes:
            label = str(raw_label).strip()
            if not label:
                continue
            key = label.casefold()
            canonical = self._canonical_lookup.get(key)
            if canonical is None:
                unmapped.append(label)
            else:
                self._canonical_counts[key] += 1
                self._canonical_restore_counts[key] = self._canonical_counts[key]
                promoted.append(canonical)
        self._unmapped = tuple(unmapped)
        return tuple(promoted)

    def selected_map_labels(self) -> tuple[str, ...]:
        return tuple(
            label for label in self._canonical if self._canonical_counts[label.casefold()] > 0
        )

    def unmapped_electrodes(self) -> tuple[str, ...]:
        return self._unmapped

    def selected_electrodes(self) -> tuple[str, ...]:
        """Merge the draft without reordering surviving or duplicate legacy tokens."""

        return self._merge_electrodes(self._canonical_counts, self._unmapped)

    def preview_electrodes(self, unmapped: Iterable[str]) -> tuple[str, ...]:
        """Preview committed fallback text without mutating the selection state."""

        canonical_counts = Counter(self._canonical_counts)
        candidate_unmapped: list[str] = []
        for raw_label in unmapped:
            label = str(raw_label).strip()
            if not label:
                continue
            key = label.casefold()
            if key in self._canonical_lookup:
                canonical_counts[key] += 1
            else:
                candidate_unmapped.append(label)
        return self._merge_electrodes(canonical_counts, candidate_unmapped)

    def _merge_electrodes(
        self,
        canonical_counts: Counter[str],
        unmapped: Iterable[str],
    ) -> tuple[str, ...]:
        """Merge candidate counts through the original ordered token ledger."""

        unmapped_values = tuple(unmapped)
        unmapped_remaining = Counter(unmapped_values)
        canonical_remaining = Counter(canonical_counts)
        selected: list[str] = []
        for original in self._original:
            key = original.casefold()
            if key in self._canonical_lookup:
                if canonical_remaining[key] > 0:
                    selected.append(original)
                    canonical_remaining[key] -= 1
                continue
            if unmapped_remaining[original] > 0:
                selected.append(original)
                unmapped_remaining[original] -= 1

        for canonical in self._canonical:
            key = canonical.casefold()
            while canonical_remaining[key] > 0:
                selected.append(canonical)
                canonical_remaining[key] -= 1

        for unmapped_label in unmapped_values:
            if unmapped_remaining[unmapped_label] > 0:
                selected.append(unmapped_label)
                unmapped_remaining[unmapped_label] -= 1
        return tuple(selected)

    def is_changed(self) -> bool:
        return self.selected_electrodes() != self._original


__all__ = [
    "BIOSEMI64_LABELS",
    "BIOSEMI64_POLAR_COORDINATES",
    "ROIElectrodeSelectionState",
    "electrode_logical_position",
    "split_electrode_text",
]
