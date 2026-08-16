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
        self.shutdown_calls = 0

    def close(self) -> None:
        self.closed += 1

    def reject(self) -> None:
        self.rejected += 1

    def deleteLater(self) -> None:  # noqa: N802 - Qt-compatible test double
        self.deleted += 1

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class _FakeSignal:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)

    def emit(self) -> None:
        for callback in tuple(self.callbacks):
            callback()


class _ActivePublicationMapsWidget(_FakeWidget):
    def __init__(self) -> None:
        super().__init__()
        self.active = True
        self.generation_idle = _FakeSignal()

    def has_active_generation(self) -> bool:
        return self.active

    def finish(self) -> None:
        self.active = False
        self.generation_idle.emit()


def test_project_context_reset_discards_embedded_pages_and_returns_home() -> None:
    workspace = _FakeWorkspace()
    settings_page = _FakeWidget()
    stats_page = _FakeWidget()
    free_harmonic_page = _FakeWidget()
    ratio_page = _FakeWidget()
    settings_dialog = _FakeWidget()
    home_calls = []
    host = SimpleNamespace(
        workspace_stack=workspace,
        _settings_dialog=settings_dialog,
        _settings_page=settings_page,
        _stats_page=stats_page,
        _free_harmonic_clustering_page=free_harmonic_page,
        _ratio_calculator_page=ratio_page,
        _individual_detectability_page=_FakeWidget(),
        _plot_generator_page=_FakeWidget(),
        show_home_page=lambda: home_calls.append("home"),
    )

    project_workflows.reset_project_context_workspace(host)

    assert home_calls == ["home"]
    assert host._settings_dialog is None
    assert host._settings_page is None
    assert host._stats_page is None
    assert host._free_harmonic_clustering_page is None
    assert host._ratio_calculator_page is None
    assert host._individual_detectability_page is None
    assert host._plot_generator_page is None
    assert settings_dialog.rejected == 1
    assert settings_dialog.deleted == 1
    assert settings_page in workspace.removed
    assert stats_page in workspace.removed
    assert free_harmonic_page in workspace.removed
    assert free_harmonic_page.shutdown_calls == 1
    assert ratio_page in workspace.removed


def test_project_context_reset_waits_for_active_scalp_maps_worker() -> None:
    workspace = _FakeWorkspace()
    publication_maps_page = _ActivePublicationMapsWidget()
    other_page = _FakeWidget()
    home_calls = []
    host = SimpleNamespace(
        workspace_stack=workspace,
        _settings_dialog=None,
        _settings_page=other_page,
        _stats_page=None,
        _free_harmonic_clustering_page=None,
        _ratio_calculator_page=None,
        _individual_detectability_page=None,
        _plot_generator_page=None,
        _publication_maps_page=publication_maps_page,
        _loreta_visualizer_page=None,
        show_home_page=lambda: home_calls.append("home"),
    )

    completed = project_workflows.reset_project_context_workspace(host)

    assert completed is False
    assert publication_maps_page.shutdown_calls == 1
    assert workspace.removed == []
    assert home_calls == []

    publication_maps_page.finish()

    assert host._publication_maps_page is None
    assert publication_maps_page in workspace.removed
    assert other_page in workspace.removed
    assert home_calls == ["home"]
