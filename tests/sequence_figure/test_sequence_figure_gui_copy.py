from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from Tools.Sequence_Figure import gui
from Tools.Sequence_Figure.gui import _image_dialog_title, _image_placeholder, _slot_label
from Tools.Sequence_Figure.renderer import SequenceFigureResult, SequenceFigureSpec


def test_image_picker_copy_labels_base_and_oddball_slots() -> None:
    assert [_image_placeholder(index) for index in range(5)] == [
        "Select base image 1",
        "Select base image 2",
        "Select base image 3",
        "Select base image 4",
        "Select Oddball Image",
    ]
    assert _image_dialog_title(0) == "Select Base Image 1"
    assert _image_dialog_title(4) == "Select Oddball Image"
    assert _image_dialog_title(0, condition=2) == "Condition 3: Select Base Image 1"
    assert _image_dialog_title(4, condition=0) == "Condition 1: Select Oddball Image"


def test_slot_labels_identify_base_and_oddball_after_an_image_is_selected() -> None:
    assert [_slot_label(index) for index in range(5)] == [
        "Base 1", "Base 2", "Base 3", "Base 4", "Oddball",
    ]


class _ControlDouble:
    def __init__(self, value: str = "", enabled: bool = False) -> None:
        self.value = value
        self.enabled = enabled

    def setText(self, value: str) -> None:
        self.value = value

    def clear(self) -> None:
        self.value = ""

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


class _SequencePageDouble:
    set_project_root = gui.SequenceFigureWindow.set_project_root
    has_active_generation = gui.SequenceFigureWindow.has_active_generation
    _apply_project_defaults = gui.SequenceFigureWindow._apply_project_defaults
    _set_output_folder = gui.SequenceFigureWindow._set_output_folder
    _suggest_dialog_dir = gui.SequenceFigureWindow._suggest_dialog_dir
    _start_export = gui.SequenceFigureWindow._start_export
    _on_failed = gui.SequenceFigureWindow._on_failed
    _on_finished = gui.SequenceFigureWindow._on_finished
    _on_thread_finished = gui.SequenceFigureWindow._on_thread_finished

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root.resolve()
        self._output_folder = ""
        self._last_result = None
        self._thread = None
        self._worker = None
        self._project_context_version = 0
        self._export_context_version = 0
        self._image_paths = [[str(project_root / "stimulus.png")]]
        self.condition_label_edits = [_ControlDouble("Manual label")]
        self.output_row = SimpleNamespace(line_edit=_ControlDouble())
        self.open_btn = _ControlDouble(enabled=True)
        self.export_btn = _ControlDouble("Rendering...")


@pytest.mark.parametrize("with_figures", [False, True])
def test_project_refresh_uses_current_root_without_discarding_inputs(
    tmp_path: Path, with_figures: bool,
) -> None:
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    old_output = old_root / "Figures"
    old_output.mkdir()
    if with_figures:
        (new_root / "Figures").mkdir()
    page = _SequencePageDouble(old_root)
    page._set_output_folder(old_output)
    page._last_result = object()
    images = page._image_paths
    labels = page.condition_label_edits
    spec = SequenceFigureSpec(image_paths=(old_root / "stimulus.png",), output_dir=old_output)
    worker = SimpleNamespace(spec=spec)
    thread = object()
    page._worker = worker
    page._thread = thread
    page._export_context_version = page._project_context_version

    page.set_project_root(str(new_root))

    expected_output = str(new_root / "Figures") if with_figures else ""
    assert page._project_root == new_root.resolve()
    assert page._output_folder == page.output_row.line_edit.value == expected_output
    assert page._suggest_dialog_dir() == str(new_root / "Figures" if with_figures else new_root)
    assert page._image_paths is images
    assert page.condition_label_edits is labels
    assert labels[0].value == "Manual label"
    assert page._last_result is None
    assert not page.open_btn.enabled
    assert page._worker is worker
    assert page._thread is thread
    assert worker.spec is spec
    assert worker.spec.output_dir == old_output
    assert page.has_active_generation()


def test_same_project_keeps_manual_output_and_projectless_refresh_clears_it(tmp_path: Path) -> None:
    manual_output = tmp_path / "manual"
    manual_output.mkdir()
    page = _SequencePageDouble(tmp_path)
    page._set_output_folder(manual_output)
    result = object()
    page._last_result = result

    page.set_project_root(str(tmp_path / "."))

    assert page._output_folder == str(manual_output)
    assert page._last_result is result
    assert page.open_btn.enabled

    page.set_project_root(None)

    assert page._project_root is None
    assert page._output_folder == page.output_row.line_edit.value == ""
    assert page._last_result is None
    assert not page.open_btn.enabled


@pytest.mark.parametrize("switch_project", [False, True])
def test_export_completion_keeps_result_in_its_project_until_thread_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, switch_project: bool,
) -> None:
    old_root = tmp_path / "old"
    old_root.mkdir()
    page = _SequencePageDouble(old_root)
    page._export_context_version = page._project_context_version
    thread = object()
    page._thread = thread
    if switch_project:
        new_root = tmp_path / "new"
        new_root.mkdir()
        page.set_project_root(str(new_root))
    notifications = []
    monkeypatch.setattr(gui, "show_info", lambda *args: notifications.append(args))
    result = SequenceFigureResult(old_root / "figure.png", old_root / "figure.pdf", None)

    page._on_finished(result)

    assert page._last_result is (None if switch_project else result)
    assert page.open_btn.enabled is (not switch_project)
    assert str(result.png_path) in notifications[0][2]
    assert page._thread is thread
    assert page.has_active_generation()
    assert not page.export_btn.enabled

    page._on_thread_finished()

    assert not page.has_active_generation()
    assert page.export_btn.enabled
    assert page.export_btn.value == "Export Figure"


def test_owned_export_thread_blocks_a_second_generation(tmp_path: Path) -> None:
    page = _SequencePageDouble(tmp_path)
    thread = object()
    page._thread = thread
    page._build_spec = lambda: pytest.fail("An owned export thread must prevent a second spec")

    page._start_export()

    assert page._thread is thread


def test_returning_to_original_project_does_not_reattach_pending_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_root = tmp_path / "old"
    old_output = old_root / "manual-output"
    old_output.mkdir(parents=True)
    default_output = old_root / "Figures"
    default_output.mkdir()
    new_root = tmp_path / "new"
    new_root.mkdir()
    page = _SequencePageDouble(old_root)
    page._set_output_folder(old_output)
    page._thread = object()
    page._export_context_version = page._project_context_version
    monkeypatch.setattr(gui, "show_info", lambda *args: None)
    result = SequenceFigureResult(old_output / "figure.png", old_output / "figure.pdf", None)

    page.set_project_root(str(new_root))
    page.set_project_root(str(old_root))
    page._on_finished(result)

    assert page._output_folder == str(default_output)
    assert page._last_result is None
    assert not page.open_btn.enabled
    assert page.has_active_generation()


def test_failed_export_retains_guard_and_allows_retry_after_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _SequencePageDouble(tmp_path)
    page._thread = object()
    page._worker = object()
    errors = []
    monkeypatch.setattr(gui, "show_error", lambda *args: errors.append(args))

    page._on_failed("Unreadable image")

    assert errors[0][1:] == ("Export Failed", "Unreadable image")
    assert page._worker is None
    assert page.has_active_generation()
    assert not page.export_btn.enabled
    assert not page.open_btn.enabled

    page._on_thread_finished()

    assert not page.has_active_generation()
    assert page.export_btn.enabled


def test_main_window_refreshes_cached_sequence_page_from_current_project(tmp_path: Path) -> None:
    source_path = Path(__file__).resolve().parents[2] / "src/Main_App/gui/main_window.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    method = next(
        method
        for node in tree.body if isinstance(node, ast.ClassDef)
        for method in node.body
        if isinstance(method, ast.FunctionDef) and method.name == "_ensure_sequence_figure_page"
    )
    namespace = {"SequenceFigureWindow": _SequencePageDouble}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source_path), "exec"), namespace)
    ensure_page = namespace["_ensure_sequence_figure_page"]
    page = _SequencePageDouble(tmp_path / "old")
    shell = SimpleNamespace(
        _sequence_figure_page=page,
        currentProject=SimpleNamespace(project_root=tmp_path / "new"),
    )

    assert ensure_page(shell) is page
    assert page._project_root == (tmp_path / "new").resolve()

    shell.currentProject = None

    assert ensure_page(shell) is page
    assert page._project_root is None
