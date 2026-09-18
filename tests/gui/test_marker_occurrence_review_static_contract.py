from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / "src" / "Main_App" / "gui" / "preprocessing_qc_workflow.py"


def _workflow_source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_marker_review_precedes_every_signal_qc_decision() -> None:
    source = _workflow_source()
    workflow = source[source.index("def run_preprocessing_qc_workflow(") :]

    initial_scan = workflow.index("scan = _run_scan_embedded(")
    marker_review = workflow.index("scan = _review_marker_occurrences(")
    condition_review = workflow.index("if not _confirm_condition_crop_exclusions(")
    condition_scoped_rescan = workflow.index(
        "scan = _run_scan_embedded(",
        condition_review,
    )
    electrode_review = workflow.index("if active_infos and not _review_removed_electrodes(")

    assert (
        initial_scan
        < marker_review
        < condition_review
        < condition_scoped_rescan
        < electrode_review
    )


def test_marker_review_rescans_only_affected_files_and_blocks_unresolved() -> None:
    source = _workflow_source()
    start = source.index("def _review_marker_occurrences(")
    stop = source.index("\ndef _review_removed_electrodes(", start)
    review = source[start:stop]

    assert "affected_infos = [" in review
    assert "rescanned = _run_scan_embedded(" in review
    assert "affected_infos," in review
    assert "collect_marker_occurrence_reviews(merged_scan)" in review
    assert "if unresolved:" in review
    assert 'params["_fpvs_marker_review_decisions_by_file"]' in review


def test_successful_workflow_hands_full_event_plans_to_analyzed_signal_qc() -> None:
    source = _workflow_source()
    workflow = source[source.index("def run_preprocessing_qc_workflow(") :]

    assert 'params["_fpvs_preflight_event_plans_by_file"]' in workflow
    event_plans = workflow.index("canonical_event_plans_by_file(")
    kurtosis_review = workflow.index("_run_kurtosis_review_scan_embedded(")
    remaining_review = workflow.index("_show_suspicious_remainder(")
    assert event_plans > workflow.index(
        "accepted_hard_exclusions = _confirm_hard_exclusions("
    )
    assert event_plans < kurtosis_review < remaining_review


def test_occurrence_review_offers_all_scientific_dispositions() -> None:
    source = _workflow_source()
    presentation = (ROOT / "src/Main_App/gui/marker_occurrence_review.py").read_text(encoding="utf-8")

    assert '"Use verified window…"' in presentation
    assert '"Keep planned window…"' in presentation
    assert '"Exclude this repetition…"' in presentation
    assert '"Cancel Processing"' in source
    assert '"marker_evidence_type_combo"' in source
    assert '"marker_evidence_note_edit"' in source
    assert '"marker_evidence_reference_edit"' in source
    assert '"marker_exclusion_reason_dialog"' in source
    assert '"marker_exclusion_reason_edit"' in source
    assert "_collect_marker_exclusion_reason(host, item)" in source


def test_marker_review_shows_sample_and_time_evidence() -> None:
    source = _workflow_source()

    assert "from recording start" in source
    assert "duration" in source


@pytest.mark.parametrize("outcome", ["exclude_occurrence", "cancel", "failure"])
def test_marker_panel_returns_choice_and_restores_shared_page(outcome):
    """Exercise the real orchestration without loading Qt or opening a window."""
    class Widget:
        def __init__(self, *, hidden=False):
            self.hidden = hidden
            self.children = []
            self.deleted = False

        def isHidden(self):
            return self.hidden

        def hide(self):
            self.hidden = True

        def show(self):
            self.hidden = False

        def setVisible(self, value):
            self.hidden = not value

        def layout(self):
            return self

        def addWidget(self, widget, _stretch):
            self.children.append(widget)

        def removeWidget(self, widget):
            self.children.remove(widget)

        def deleteLater(self):
            self.deleted = True

    class Signal:
        def connect(self, callback):
            self.callback = callback

    panels = []
    pages = []
    host = SimpleNamespace(
        processing_files_card=Widget(), processing_status_card=Widget(),
        processing_files_title_label=Widget(hidden=True), processing_files_table=Widget(),
    )

    class Panel(Widget):
        def __init__(self, item, parent, **kwargs):
            super().__init__()
            self.choice_requested = Signal()
            self.item = item
            self.arguments = kwargs
            panels.append(self)

    class Loop:
        def __init__(self, _host):
            pass

        def exec(self):
            assert host.processing_status_card.hidden
            assert host.processing_files_table.hidden
            assert host.processing_files_title_label.hidden
            assert host.processing_files_card.children == panels
            if outcome == "failure":
                raise RuntimeError("simulated panel failure")
            panels[0].choice_requested.callback(outcome)

        def quit(self):
            pass

    function = next(node for node in ast.parse(_workflow_source()).body
                    if isinstance(node, ast.FunctionDef) and node.name == "_show_marker_occurrence_review")
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), function], type_ignores=[])
    namespace = {
        "_begin_preflight_page": lambda _host, **kwargs: pages.append(kwargs),
        "_clear_preflight_actions": lambda _host: None,
        "_REVIEW_MARKER_OCCURRENCES_STEP": 2,
        "MarkerOccurrenceReviewPanel": Panel, "QEventLoop": Loop,
    }
    exec(compile(ast.fix_missing_locations(module), str(WORKFLOW), "exec"), namespace)
    item = object()
    if outcome == "failure":
        with pytest.raises(RuntimeError, match="simulated panel failure"):
            namespace[function.name](host, item, index=2, total=3, group_label="Control")
    else:
        assert namespace[function.name](host, item, index=2, total=3, group_label="Control") == outcome
    assert not host.processing_status_card.hidden
    assert not host.processing_files_table.hidden
    assert host.processing_files_title_label.hidden
    assert host.processing_files_card.children == []
    assert panels[0].hidden and panels[0].deleted
    assert panels[0].item is item
    assert panels[0].arguments == {"index": 2, "total": 3, "group_label": "Control"}
    assert pages[0].get("checklist", ()) == ()
