"""First-use disclosure and the app-local Diagnostics preferences page."""

from __future__ import annotations

import logging
import sqlite3

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QHBoxLayout, QLabel, QTabWidget, QVBoxLayout, QWidget

from Main_App.diagnostics.crash_reporting import DISCLOSURE, CrashReporter, current_reporter
from Main_App.gui.components import SubsectionHeaderLabel, make_action_button, show_error
from Main_App.gui.icons import application_icon
from Main_App.gui.style_tokens import SECTION_GAP, SECTION_HEADER_CONTENT_GAP
from Main_App.gui.theme import set_themed_stylesheet
from Main_App.gui.typography import css_font_size, css_font_weight

_LOGGER = logging.getLogger(__name__)
_PREFERENCE_ERRORS = (OSError, sqlite3.Error, ValueError)


def _build_reporting_disclosure() -> QDialog:
    dialog = QDialog()
    dialog.setObjectName("automatic_reporting_disclosure")
    dialog.setWindowTitle("Automatic error and crash reporting")
    dialog.setProperty("fpvsSurface", True)
    dialog.setMinimumWidth(560)
    icon = application_icon()
    dialog.setWindowIcon(icon)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(24, 24, 24, 24)
    layout.setSpacing(16)

    header = QHBoxLayout()
    header.setSpacing(12)
    logo = QLabel(dialog)
    logo.setPixmap(icon.pixmap(QSize(44, 44), dialog.devicePixelRatioF()))
    header.addWidget(logo)
    title = QLabel(dialog.windowTitle(), dialog)
    title.setWordWrap(True)
    set_themed_stylesheet(
        title, f"font-size: {css_font_size('project_title')}; font-weight: {css_font_weight('project_title')};"
    )
    header.addWidget(title, 1)
    layout.addLayout(header)

    sections = (
        (None, "FPVS Toolbox can send error and crash reports automatically to the private OpenFPVS feedback service."),
        (
            "What reports include",
            "Toolbox and operating system versions, available hardware model, CPU and graphics models, memory, "
            "relevant software versions, and the time and type of failure with a short list of code locations.",
        ),
        (
            "What stays local",
            "Project and EEG data, filenames and paths, full logs, and personal and device identifiers.",
        ),
        (
            None,
            "You can turn reporting off in Settings › Diagnostics at any time. Turning it off deletes pending reports.",
        ),
    )
    for heading, text in sections:
        section = QVBoxLayout()
        section.setSpacing(4)
        if heading:
            section.addWidget(SubsectionHeaderLabel(heading, dialog))
        body = QLabel(text, dialog)
        body.setTextFormat(Qt.PlainText)
        body.setWordWrap(True)
        section.addWidget(body)
        layout.addLayout(section)

    layout.addStretch(1)
    actions = QHBoxLayout()
    actions.setSpacing(10)
    actions.addStretch(1)
    decline = make_action_button("Keep reporting off", parent=dialog)
    decline.setObjectName("automatic_reporting_decline")
    decline.clicked.connect(dialog.reject)
    enable = make_action_button("Enable automatic reporting", variant="primary", parent=dialog)
    enable.setObjectName("automatic_reporting_enable")
    enable.clicked.connect(dialog.accept)
    for button in (decline, enable):
        button.setMinimumHeight(40)
        actions.addWidget(button)
    enable.setDefault(True)
    enable.setFocus()
    layout.addLayout(actions)
    dialog.resize(dialog.minimumWidth(), layout.totalHeightForWidth(dialog.minimumWidth()))
    return dialog


def disclose_automatic_reporting(reporter: CrashReporter) -> None:
    try:
        if reporter.preference() is not None:
            return
        disclosure = _build_reporting_disclosure()
        quit_on_close = QApplication.quitOnLastWindowClosed()
        QApplication.setQuitOnLastWindowClosed(False)
        try:
            decision = disclosure.exec()
        finally:
            QApplication.setQuitOnLastWindowClosed(quit_on_close)
        reporter.set_preference(decision == QDialog.DialogCode.Accepted)
    except _PREFERENCE_ERRORS:
        _LOGGER.warning("automatic_crash_disclosure_unavailable")


def build_diagnostics_page(tabs: QTabWidget) -> None:
    tab = QWidget()
    tab.setObjectName("settings_diagnostics_tab")
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(0, SECTION_HEADER_CONTENT_GAP, 0, 0)
    layout.setSpacing(SECTION_GAP)
    layout.addWidget(SubsectionHeaderLabel("Automatic error and crash reporting", tab))

    explanation = QLabel(DISCLOSURE, tab)
    explanation.setTextFormat(Qt.PlainText)
    explanation.setWordWrap(True)
    layout.addWidget(explanation)

    toggle = QCheckBox("Send error and crash reports automatically", tab)
    toggle.setObjectName("settings_automatic_crash_reporting")
    reporter = current_reporter()
    try:
        committed = reporter.preference() is True if reporter is not None else False
    except _PREFERENCE_ERRORS:
        reporter = None
        committed = False
    toggle.setChecked(committed)
    toggle.setEnabled(reporter is not None)

    def set_reporting(enabled: bool) -> None:
        nonlocal committed
        try:
            reporter.set_preference(enabled)
            committed = enabled
        except _PREFERENCE_ERRORS:
            _LOGGER.warning("automatic_crash_preference_save_failed")
            previous = toggle.blockSignals(True)
            toggle.setChecked(committed)
            toggle.blockSignals(previous)
            show_error(tab, "Reporting preference unavailable", "Could not save the automatic reporting preference.")

    if reporter is not None:
        toggle.toggled.connect(set_reporting)
    layout.addWidget(toggle)
    status = QLabel("Applies immediately." if reporter else "Automatic reporting is unavailable.", tab)
    layout.addWidget(status)
    layout.addStretch(1)
    tabs.addTab(tab, "Diagnostics")
