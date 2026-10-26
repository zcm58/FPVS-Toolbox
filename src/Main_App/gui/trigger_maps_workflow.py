"""Ownership, atomic publication and Home presentation for source trigger maps."""

from __future__ import annotations

from copy import deepcopy
import json

from PySide6.QtWidgets import QDialog, QLabel

from Main_App.gui.components import show_error, show_info
from Main_App.projects.condition_trigger_maps import TriggerMapDraft, project_conditions
from Main_App.projects.manifest_store import project_manifest_transaction
from Main_App.projects.preprocessing_settings import normalize_preprocessing_settings
from Main_App.processing.pipeline_settings_freshness import apply_pipeline_setup_freshness
from .project_drafts import has_condition_changes, remember_saved_setup
from .toolbox_cache_workflow import _cache_work_is_active
from .trigger_maps_model import trigger_maps_summary


def refresh_home_trigger_maps(host):
    project = getattr(host, "currentProject", None)
    maps = getattr(getattr(project, "frequency_protocol", None), "condition_trigger_maps", None)
    mapped = maps is not None
    layout = getattr(host, "event_layout", None)
    if layout is not None:
        for index in reversed(range(layout.count())):
            widget = layout.itemAt(index).widget()
            if widget is not None and widget.property("source_trigger_catalog"):
                layout.takeAt(index)
                widget.deleteLater()
    for name in ("event_id_header", "event_actions_header", "btn_add_row"):
        widget = getattr(host, name, None)
        if widget is not None:
            widget.setVisible(not mapped)
    button = getattr(host, "trigger_maps_button", None)
    if button is not None:
        button.setText("Trigger maps…" if mapped else "Use source maps…")
        button.setEnabled(project is not None)
        button.setToolTip(trigger_maps_summary(project.frequency_protocol) if project is not None else "Open a project first.")
    if not mapped:
        return
    layout = host.event_layout
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().deleteLater()
    host.event_rows.clear()
    summary = QLabel(trigger_maps_summary(project.frequency_protocol), host.event_container)
    summary.setObjectName("home_trigger_maps_summary")
    summary.setProperty("source_trigger_catalog", True)
    layout.addWidget(summary)
    for condition in project_conditions(project):
        label = QLabel(condition.label, host.event_container)
        label.setProperty("source_trigger_catalog", True)
        label.setToolTip(f"Condition ID: {condition.condition_id}")
        layout.addWidget(label)
    remember_saved_setup(host)


def save_trigger_map_draft(project, draft):
    """Do not mutate the live project until all validation and disk I/O succeed."""
    with project_manifest_transaction(project.manifest_path) as transaction:
        current = json.loads(project.manifest_path.read_text(encoding="utf-8"))
        # Also reject a changed live model, even if its edits have not reached disk.
        live = deepcopy(project.manifest)
        live["event_map"] = deepcopy(project.event_map)
        live["frequency_protocol"] = project.frequency_protocol.to_manifest()
        draft.apply_to_manifest(live)
        candidate = draft.apply_to_manifest(current)
        apply_pipeline_setup_freshness(candidate, current)
        preprocessing = normalize_preprocessing_settings(candidate.get("preprocessing"))
        transaction.write(candidate)
    project.event_map = {}
    project.preprocessing = preprocessing
    project.manifest = candidate
    project.update_frequency_protocol(candidate["frequency_protocol"])
    project._trigger_configuration_baseline = deepcopy({
        "frequency_protocol": candidate.get("frequency_protocol"), "event_map": candidate.get("event_map", {}),
    })


def show_home_trigger_maps(host):
    project = getattr(host, "currentProject", None)
    if project is None:
        return
    if _cache_work_is_active(host):
        show_info(host, "Trigger maps unavailable", "Wait for processing and tool work to finish before editing trigger maps.")
        return
    settings = getattr(host, "_settings_page", None)
    if has_condition_changes(host) or (settings is not None and settings.has_unsaved_changes()):
        show_info(host, "Unsaved project edits", "Save or cancel your condition and Settings edits before editing trigger maps.")
        return
    from .trigger_maps_dialog import TriggerMapsDialog

    try:
        draft = TriggerMapDraft.from_project(project, allow_empty=True)
        dialog = TriggerMapsDialog(project, host, payload=draft.payload)
    except ValueError as exc:
        show_error(host, "Trigger maps unavailable", str(exc))
        return
    try:
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        draft.payload = dialog.maps().to_manifest()
        save_trigger_map_draft(project, draft)
    except (ValueError, OSError, RuntimeError) as exc:
        show_error(host, "Trigger maps were not saved", str(exc))
        return
    finally:
        dialog.deleteLater()
    # This page was confirmed clean above; discard its obsolete controls now.
    if settings is not None:
        settings.reject()
    refresh_home_trigger_maps(host)
    host._update_start_enabled()


def show_source_participants(host):
    if _cache_work_is_active(host):
        show_info(host, "Registration unavailable", "Wait for processing and tool work to finish before registering participants.")
        return
    settings = getattr(host, "_settings_page", None)
    if has_condition_changes(host) or (settings is not None and settings.has_unsaved_changes()):
        show_info(host, "Unsaved project edits", "Save or cancel your condition and Settings edits before registering participants.")
        return
    from Main_App.projects.project_manager import register_source_participants

    register_source_participants(host)
