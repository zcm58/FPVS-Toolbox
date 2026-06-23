from __future__ import annotations

from types import SimpleNamespace

from Main_App.gui import project_workflows


class _FakeWorkspace:
    def __init__(self) -> None:
        self.removed = []

    def removeWidget(self, widget) -> None:  # noqa: N802 - Qt-compatible test double
        self.removed.append(widget)


class _FakeWidget:
    def __init__(self) -> None:
        self.closed = 0
        self.rejected = 0
        self.deleted = 0

    def close(self) -> None:
        self.closed += 1

    def reject(self) -> None:
        self.rejected += 1

    def deleteLater(self) -> None:  # noqa: N802 - Qt-compatible test double
        self.deleted += 1


def test_project_context_reset_discards_embedded_pages_and_returns_home() -> None:
    workspace = _FakeWorkspace()
    settings_page = _FakeWidget()
    stats_page = _FakeWidget()
    ratio_page = _FakeWidget()
    publication_report_page = _FakeWidget()
    epoch_page = _FakeWidget()
    settings_dialog = _FakeWidget()
    home_calls = []
    host = SimpleNamespace(
        workspace_stack=workspace,
        _settings_dialog=settings_dialog,
        _settings_page=settings_page,
        _stats_page=stats_page,
        _image_resizer_page=_FakeWidget(),
        _ratio_calculator_page=ratio_page,
        _individual_detectability_page=_FakeWidget(),
        _plot_generator_page=_FakeWidget(),
        _epoch_page=epoch_page,
        _epoch_win=epoch_page,
        _publication_report_page=publication_report_page,
        show_home_page=lambda: home_calls.append("home"),
    )

    project_workflows.reset_project_context_workspace(host)

    assert home_calls == ["home"]
    assert host._settings_dialog is None
    assert host._settings_page is None
    assert host._stats_page is None
    assert host._image_resizer_page is None
    assert host._ratio_calculator_page is None
    assert host._individual_detectability_page is None
    assert host._plot_generator_page is None
    assert host._publication_report_page is None
    assert host._epoch_page is None
    assert host._epoch_win is None
    assert settings_dialog.rejected == 1
    assert settings_dialog.deleted == 1
    assert settings_page in workspace.removed
    assert stats_page in workspace.removed
    assert ratio_page in workspace.removed
    assert publication_report_page in workspace.removed
    assert epoch_page in workspace.removed
    assert epoch_page.closed == 1
    assert epoch_page.deleted == 1
