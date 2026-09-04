from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from Tools.Plot_Generator.analysis_context import SNRAnalysisContext
from Tools.Plot_Generator import output_interface


class _Host(output_interface.PlotOutputInterfaceMixin):
    def __init__(self, *, explicit: bool, oddballs: list[float]) -> None:
        self._initialize_plot_output_interface()
        self._analysis_base_freq = 6.0
        self._analysis_oddball_freq = 1.2
        self._explicit_oddballs = explicit
        self.oddballs = oddballs
        self.x_max = 20.0
        self.warnings = []

    def _derive_oddball_harmonics(self, _max_hz: float) -> list[float]:
        return [1.2, 2.4, 3.6]

    def _record_warning(self, **warning) -> None:
        self.warnings.append(warning)

    def _emit(self, *_args, **_kwargs) -> None:
        return None


def _context() -> SNRAnalysisContext:
    return SNRAnalysisContext(
        project_root=Path("."),
        base_frequency_hz=10.0,
        oddball_frequency_hz=2.0,
        allowed_workbook_paths=frozenset(),
        provenance={"source_kind": "managed_full_fft_provenance"},
        eligible_oddball_frequencies_hz=(2.0, 4.0, 8.0),
        eligible_frequency_upper_hz=10.0,
        spectral_eligibility_fingerprint="eligibility",
    )


def test_managed_context_replaces_derived_stems_with_eligible_oddballs(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        output_interface,
        "resolve_snr_analysis_context",
        lambda *_args, **_kwargs: _context(),
    )
    host = _Host(explicit=False, oddballs=[1.2, 2.4, 3.6])

    host._configure_analysis_context(
        SimpleNamespace(manifest={}, project_root=Path("."))
    )

    assert host.oddballs == [2.0, 4.0, 8.0]


def test_managed_explicit_stems_are_intersected_with_technical_eligibility(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        output_interface,
        "resolve_snr_analysis_context",
        lambda *_args, **_kwargs: _context(),
    )
    host = _Host(explicit=True, oddballs=[2.0, 6.0, 8.0])

    host._configure_analysis_context(
        SimpleNamespace(manifest={}, project_root=Path("."))
    )

    assert host.oddballs == [2.0, 8.0]
