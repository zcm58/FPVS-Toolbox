"""Project cache controls and asynchronous usage for the Performance tab."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtWidgets import QCheckBox, QGridLayout, QLabel

from Main_App.gui.components import SectionCard, SubsectionHeaderLabel
from Main_App.processing.project_processing_cache import inspect_recording_cache_usage


logger = logging.getLogger(__name__)


class _CacheUsageSignals(QObject):
    finished = Signal(object)


class _CacheUsageJob(QRunnable):
    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root
        self.signals = _CacheUsageSignals()

    def run(self) -> None:
        try:
            usage = inspect_recording_cache_usage(self.root)
        except (OSError, ValueError):
            logger.warning("recording_cache_usage_failed project=%s", self.root, exc_info=True)
            usage = {}
        self.signals.finished.emit(usage)


class RecordingCachesSection(SectionCard):
    def __init__(self, settings, parent, preprocessing) -> None:
        super().__init__("Recording caches", parent, object_name="settings_recording_caches")
        self._root = settings.project.project_root if settings.project is not None else None
        self._usage_job: _CacheUsageJob | None = None
        self._usage_labels: dict[str, QLabel] = {}

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        for column, title in enumerate(("Cache", "Time saved", "Disk per recording", "On disk")):
            grid.addWidget(SubsectionHeaderLabel(title, self), 0, column)

        for row, (key, label, time, size, description) in enumerate((
            (
                "enable_bids_import_cache", "BIDS imports", "~8 s copying and setup", "~440 MB",
                "When off, Toolbox uses a temporary import for the recording.",
            ),
            (
                "enable_kurtosis_checkpoint_cache", "Kurtosis review checkpoints", "~15 s preparation", "~130 MB",
                "Without a prepared checkpoint, the waveform viewer can show the initial-reference signal.",
            ),
            (
                "enable_preprocessed_cache", "Preprocessed EEG (FIF)", "~8 s processing", "~135 MB",
                "The disk estimate is for double-precision FIF.",
            ),
        ), start=1):
            check = QCheckBox(label, self)
            check.setObjectName(f"settings_{key}")
            check.setChecked(bool(preprocessing.get(key, True)))
            check.setEnabled(self._root is not None)
            check.setToolTip(description)
            check.setAccessibleDescription(f"Estimated {time} and {size} per recording. {description}")
            setattr(settings, f"{key}_check", check)
            grid.addWidget(check, row, 0)
            grid.addWidget(QLabel(time, self), row, 1)
            grid.addWidget(QLabel(size, self), row, 2)
            usage = QLabel("—", self)
            usage.setObjectName(f"settings_{key}_usage")
            usage.setAccessibleName(f"{label} retained storage")
            self._usage_labels[key] = usage
            grid.addWidget(usage, row, 3)

        self.content_layout.addLayout(grid)
        settings._add_settings_scope(
            self.content_layout,
            "MCCTR estimates per recording. Kurtosis uses one replay. "
            "FIF time averages a 69-recording parallel run using single precision.",
        )
        settings._add_settings_scope(
            self.content_layout,
            "Changes apply to the next run. Turning a cache off keeps files already on disk."
            if self._root is not None else "Open a project to change cache settings.",
        )

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._root is None or self._usage_job is not None:
            return
        for label in self._usage_labels.values():
            label.setText("Checking…")
        job = _CacheUsageJob(self._root)
        job.signals.finished.connect(self._set_usage, Qt.ConnectionType.QueuedConnection)
        self._usage_job = job
        QThreadPool.globalInstance().start(job)

    @Slot(object)
    def _set_usage(self, usage: dict[str, int | None]) -> None:
        self._usage_job = None
        for key, label in self._usage_labels.items():
            size = usage.get(key)
            if size is None:
                label.setText("Unavailable")
            elif size >= 1_000_000_000:
                label.setText(f"{size / 1_000_000_000:.1f} GB")
            elif 0 < size < 1_000_000:
                label.setText("<1 MB")
            else:
                label.setText(f"{size / 1_000_000:.1f} MB")
