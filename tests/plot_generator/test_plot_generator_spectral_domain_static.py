from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _method_source(path: Path, class_name: str, method_name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    owner = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method = next(
        node
        for node in owner.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == method_name
    )
    return ast.unparse(method)


def test_plot_gui_has_no_live_bca_ceiling_default() -> None:
    path = ROOT / "src" / "Tools" / "Plot_Generator" / "gui.py"
    source = path.read_text(encoding="utf-8")

    assert "bca_upper_limit" not in source
    assert "project_plot_default_upper_hz(self._project)" in source


def test_managed_plot_annotations_use_canonical_technical_eligibility() -> None:
    path = ROOT / "src" / "Tools" / "Plot_Generator" / "output_interface.py"
    source = _method_source(
        path,
        "PlotOutputInterfaceMixin",
        "_configure_analysis_context",
    )

    assert "context.eligible_oddball_frequencies_hz" in source
    assert "selected_harmonics" not in source
    assert "self._derive_oddball_harmonics" in source


def test_plot_worker_clamps_display_to_observed_frequency_range() -> None:
    path = ROOT / "src" / "Tools" / "Plot_Generator" / "worker.py"
    source = _method_source(path, "_Worker", "_clamp_x_max_to_observed_frequency_grid")

    assert "observed_upper = max(observed)" in source
    assert "self.x_max = observed_upper" in source


def test_fhc_snapshot_uses_project_protocol_not_application_settings() -> None:
    path = ROOT / "src" / "Main_App" / "gui" / "main_window.py"
    source = _method_source(path, "MainWindow", "_free_harmonic_frequency_snapshot")

    assert "normalize_frequency_protocol(project.frequency_protocol)" in source
    assert "self.settings.get" not in source
