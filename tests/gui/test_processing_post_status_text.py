import re
from types import SimpleNamespace

from Main_App.gui import shell_status
from Main_App.gui.processing_workflows import (
    _PostProcessingPipelineBridge,
    _post_processing_display_state,
    _post_processing_phase_display_state,
    _refresh_cached_loreta_source_maps,
)
from Main_App.gui.style_tokens import build_main_page_stylesheet


class _FakeWidget:
    def __init__(self, *, visible: bool = True) -> None:
        self.visible = visible

    def setVisible(self, visible: bool) -> None:
        self.visible = bool(visible)


class _FakeLabel(_FakeWidget):
    def __init__(self, text: str = "", *, visible: bool = True) -> None:
        super().__init__(visible=visible)
        self.text = text

    def setText(self, text: str) -> None:
        self.text = str(text)


class _FakeProgressBar(_FakeWidget):
    def __init__(self) -> None:
        super().__init__()
        self.minimum = 0
        self.maximum = 100
        self.value = 100
        self.format = "%p%"

    def setRange(self, minimum: int, maximum: int) -> None:
        self.minimum = int(minimum)
        self.maximum = int(maximum)

    def setValue(self, value: int) -> None:
        self.value = int(value)

    def setFormat(self, text: str) -> None:
        self.format = str(text)


class _FakeAnimation:
    def __init__(self) -> None:
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1


def test_post_processing_perf_progress_is_user_facing_harmonic_text() -> None:
    title, message = _post_processing_display_state(
        "[PERF] Group policy BCA aggregation progress: 10/126 workbooks "
        "(participant=P10, condition=Neutral Happy, last_read=0.02s, elapsed=0.22s)."
    )

    assert title == "Identifying Significant Harmonics"
    assert message == "FPVS Toolbox is currently identifying significant harmonics."
    assert "[PERF]" not in message


def test_post_processing_fullfft_source_progress_is_user_facing_source_map_text() -> None:
    title, message = _post_processing_display_state(
        "Reading participant FullFFT workbooks and selected harmonics..."
    )

    assert title == "Generating Source Maps"
    assert message == "Generating source-space maps for 3D visualization of oddball responses."


def test_structured_post_processing_phase_avoids_log_keyword_misclassification() -> None:
    title, message, phase_index = _post_processing_phase_display_state(
        "stats_ready_export",
        "FPVS Toolbox is preparing analysis files for downstream tools.",
    )

    assert title == "Preparing Analysis Outputs"
    assert message == "FPVS Toolbox is preparing analysis files for downstream tools."
    assert phase_index == 3


def test_post_processing_activity_hides_file_rows_and_restarts_progress() -> None:
    animation = _FakeAnimation()
    progress_bar = _FakeProgressBar()
    host = SimpleNamespace(
        processing_files_card=_FakeWidget(),
        processing_status_card=_FakeWidget(visible=False),
        processing_progress_heading_label=_FakeLabel(),
        processing_step_label=_FakeLabel(visible=False),
        progress_bar=progress_bar,
        _progress_anim=animation,
    )

    shell_status.prepare_post_processing_activity(host)

    assert host.processing_files_card.visible is False
    assert host.processing_status_card.visible is True
    assert host.processing_progress_heading_label.text == "Post-Processing Progress"
    assert (progress_bar.minimum, progress_bar.maximum, progress_bar.value) == (0, 100, 0)
    assert animation.stop_calls == 1

    shell_status.update_post_processing_progress(
        host,
        completed_units=1,
        total_units=5,
        phase_index=2,
    )

    assert progress_bar.value == 20
    assert host.processing_step_label.text == "Post-processing phase 2 of 5"


def test_post_processing_qc_resume_preserves_completed_qc_milestone() -> None:
    progress_bar = _FakeProgressBar()
    host = SimpleNamespace(
        processing_files_card=_FakeWidget(),
        processing_status_card=_FakeWidget(),
        processing_progress_heading_label=_FakeLabel(),
        processing_step_label=_FakeLabel(),
        progress_bar=progress_bar,
        _progress_anim=_FakeAnimation(),
    )

    shell_status.prepare_post_processing_activity(host, initial_progress_pct=20)
    shell_status.update_post_processing_progress(
        host,
        completed_units=0,
        total_units=5,
        phase_index=1,
        minimum_completed_units=1,
    )

    assert progress_bar.value == 20
    assert host.processing_step_label.text == "Post-processing phase 1 of 5"


def test_post_processing_bridge_forwards_structured_phase_progress() -> None:
    received: list[tuple[str, int, int, str]] = []
    bridge = _PostProcessingPipelineBridge(
        progress_callback=lambda _message: None,
        phase_progress_callback=lambda *args: received.append(args),
        log_callback=lambda _message, _level: None,
        finished_callback=lambda _result: None,
        parent=None,
    )

    bridge.handle_phase_progress("harmonic_selection", 1, 5, "Identifying harmonics")

    assert received == [("harmonic_selection", 1, 5, "Identifying harmonics")]


def test_post_processing_refreshes_only_an_existing_loreta_page() -> None:
    calls: list[str] = []
    page = SimpleNamespace(
        reload_project_source_maps_from_disk=lambda: calls.append("reload") or True
    )

    assert _refresh_cached_loreta_source_maps(SimpleNamespace()) is False
    assert (
        _refresh_cached_loreta_source_maps(
            SimpleNamespace(_loreta_visualizer_page=page)
        )
        is True
    )
    assert calls == ["reload"]


def test_post_processing_loreta_refresh_failure_does_not_break_completion() -> None:
    def _raise_deleted_page() -> bool:
        raise RuntimeError("wrapped C/C++ object has been deleted")

    page = SimpleNamespace(
        reload_project_source_maps_from_disk=_raise_deleted_page,
    )

    assert (
        _refresh_cached_loreta_source_maps(
            SimpleNamespace(_loreta_visualizer_page=page)
        )
        is False
    )


def test_processing_progress_bar_style_removes_inset_frame() -> None:
    stylesheet = build_main_page_stylesheet()
    match = re.search(r"#processing_progress_bar\s*\{(?P<body>[^}]*)\}", stylesheet)

    assert match is not None
    body = match.group("body")
    assert "border: none;" in body
    assert "padding: 0;" in body


def test_processing_activity_styles_do_not_define_nested_card_frames() -> None:
    stylesheet = build_main_page_stylesheet()

    assert "#processing_activity_header" not in stylesheet
    assert "#processing_status_card" not in stylesheet
    assert "#processing_files_card" not in stylesheet
    assert 'QWidget[processingSection="true"]' not in stylesheet

    table_match = re.search(
        r"#processing_files_table\s*\{(?P<body>[^}]*)\}",
        stylesheet,
    )
    assert table_match is not None
    table_body = table_match.group("body")
    assert "border: none;" in table_body
    assert "border-radius: 0;" in table_body
