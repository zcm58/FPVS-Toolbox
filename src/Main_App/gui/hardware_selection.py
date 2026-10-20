"""Explicit project hardware confirmation shared by setup and processing."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from PySide6.QtWidgets import QInputDialog, QMessageBox

from Main_App.projects.hardware import (
    HARDWARE_LABELS, confirm_hardware_selection, detect_hardware_from_paths,
    require_hardware_ready, resolve_hardware,
)


def confirm_hardware_change(parent: Any, previous: str, selected: str) -> bool:
    if previous == selected:
        return True
    return QMessageBox.warning(
        parent, "Change Project EEG Hardware?",
        f"Change this project from {HARDWARE_LABELS[previous]} to {HARDWARE_LABELS[selected]}?\n\n"
        "An incorrect hardware setting can break Toolbox functionality and produce invalid results. "
        "Reference and montage settings will be reset for the selected platform. "
        "Existing results must be reprocessed before use.",
        QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
    ) == QMessageBox.Yes


def choose_new_project_hardware(parent: Any, settings: dict[str, Any]) -> dict[str, Any] | None:
    selected, accepted = QInputDialog.getItem(
        parent, "Project EEG Hardware", "Select the EEG hardware used for data collection:",
        list(HARDWARE_LABELS.values()), 0, False,
    )
    if not accepted:
        return None
    platform = next(key for key, value in HARDWARE_LABELS.items() if value == selected)
    return confirm_hardware_selection(settings, platform, confirmed_change=True)


def ensure_project_hardware_ready(host: Any, paths: Iterable[str | Path]) -> bool:
    """Confirm detected formats and persist one platform before any processing."""
    project = getattr(host, "currentProject", None)
    if project is None:
        return False
    paths = tuple(paths)
    try:
        project.refresh_electrode_geometry_settings()
        current = resolve_hardware(project.preprocessing)
        detected = detect_hardware_from_paths(paths)
        if current.confirmed and (detected is None or detected == current.platform):
            require_hardware_ready(project.preprocessing, paths)
            return True
        proposed = detected or current.platform
        if current.platform != proposed and current.confirmed:
            if not confirm_hardware_change(host, current.platform, proposed):
                return False
        else:
            if detected is None:
                selected, accepted = QInputDialog.getItem(
                    host, "Confirm Project EEG Hardware", "EEG hardware used for data collection:",
                    list(HARDWARE_LABELS.values()),
                    list(HARDWARE_LABELS).index(current.platform), False,
                )
                if not accepted:
                    return False
                proposed = next(key for key, label in HARDWARE_LABELS.items() if label == selected)
                response = QMessageBox.Yes
            else:
                response = QMessageBox.question(
                    host, "Confirm Project EEG Hardware",
                    f"The selected recording format indicates {HARDWARE_LABELS[proposed]}.\n\n"
                    "Was this the EEG hardware used for data collection? "
                    "The choice will be saved for this project.",
                    QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
                )
            if response != QMessageBox.Yes:
                return False
        updated = confirm_hardware_selection(project.preprocessing, proposed, confirmed_change=True)
        require_hardware_ready(updated, paths)
        snapshot = deepcopy(vars(project))
        try:
            project.update_preprocessing(updated)
            project.save()
        except Exception:  # Transaction boundary: restore in-memory state, then propagate every save failure.
            project.__dict__.clear()
            project.__dict__.update(snapshot)
            raise
        require_hardware_ready(project.preprocessing, paths)
        return True
    except (OSError, ValueError) as exc:
        QMessageBox.warning(host, "Project EEG Hardware", str(exc))
        return False
