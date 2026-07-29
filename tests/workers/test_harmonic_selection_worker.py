from pathlib import Path
from types import SimpleNamespace

import pytest

from Main_App.workers import harmonic_selection_worker


pytestmark = pytest.mark.qt


def test_settings_worker_forces_transactional_harmonic_recalculation(
    qtbot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    report = SimpleNamespace(
        workbook_path=Path("Quality Check") / "Harmonic_Selection_Summary.xlsx",
        selection_metadata={"selected_harmonics_hz": [1.2]},
        messages=("recalculated",),
    )

    def _run(project, **kwargs):
        calls.append({"project": project, **kwargs})
        return report

    monkeypatch.setattr(
        harmonic_selection_worker,
        "run_processing_harmonic_selection_qc",
        _run,
    )
    project = object()
    worker = harmonic_selection_worker.ProcessingHarmonicSelectionWorker(project)

    with qtbot.waitSignal(worker.finished) as blocker:
        worker.run()

    assert len(calls) == 1
    assert calls[0]["project"] is project
    assert callable(calls[0]["log_func"])
    assert calls[0]["force_recalculate"] is True
    assert blocker.args[0]["ok"] is True
