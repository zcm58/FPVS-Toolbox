"""Outside-file protection for project-owned persistence writers."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from functools import partial

import numpy as np
import pytest


JSON_WRITERS = (
    "Tools.LORETA_Visualizer.source_producers.l2_mne_cortical",
    "Tools.LORETA_Visualizer.source_producers.l2_mne_hauk_zscore",
    "Tools.LORETA_Visualizer.source_producers.eloreta_volume",
    "Tools.LORETA_Visualizer.source_producers.source_validation_report",
)


def _plant_staging_link(tmp_path: Path, staging: Path, kind: str) -> tuple[Path, bytes]:
    victim = tmp_path / "outside.txt"
    before = b'{"preserved": "outside content"}\n'
    victim.write_bytes(before)
    if kind == "hardlink":
        os.link(victim, staging)
    else:
        try:
            staging.symlink_to(victim)
        except OSError as exc:
            if os.name == "nt" and exc.winerror == 1314:
                pytest.skip("Windows symlink creation requires additional privileges")
            raise
    return victim, before


@pytest.mark.parametrize("kind", ["hardlink", "symlink"])
@pytest.mark.parametrize("writer_module", JSON_WRITERS)
def test_source_json_writers_do_not_follow_predictable_staging_links(tmp_path, kind, writer_module):
    folder = tmp_path / "output"
    folder.mkdir()
    target = folder / "source.json"
    staging = target.with_suffix(".json.tmp")
    victim, before = _plant_staging_link(tmp_path, staging, kind)

    importlib.import_module(writer_module)._write_json(target, {"published": True})

    assert victim.read_bytes() == before
    assert staging.read_bytes() == before
    assert json.loads(target.read_bytes()) == {"published": True}
    assert set(folder.iterdir()) == {target, staging}


@pytest.mark.parametrize("kind", ["hardlink", "symlink"])
@pytest.mark.parametrize("writer", ["ledger", "detectability", "fhc_exclusions", "fhc_plan", "source_report_text"])
def test_managed_writers_preserve_outside_staging_targets(tmp_path, kind, writer):
    folder = tmp_path / "project"
    folder.mkdir()
    if writer == "ledger":
        from Main_App.processing.processing_ledger import ledger_path, save_ledger
        target = ledger_path(folder)
        operation = partial(save_ledger, folder, {"entries": {"P01": {}}})
    elif writer == "detectability":
        from Tools.Individual_Detectability.core import _save_cache_npz
        target = folder / "participant.npz"
        operation = partial(_save_cache_npz,
            target, pid="P01", n_sig=1, z_topo=np.ones(2), snr_x=None, snr_y=None,
        )
    elif writer == "fhc_exclusions":
        from Tools.Free_Harmonic_Clustering.gui.exclusion_state import (
            exclusion_state_path, save_project_recording_exclusions,
        )
        target = exclusion_state_path(folder)
        operation = partial(save_project_recording_exclusions, folder, [])
    elif writer == "fhc_plan":
        from Tools.Free_Harmonic_Clustering.gui.analysis_plan_state import (
            ANALYSIS_PLAN_STATE_FILENAME, AnalysisPlanPreferences, save_analysis_plan_preferences,
        )
        target = folder / ANALYSIS_PLAN_STATE_FILENAME
        operation = partial(save_analysis_plan_preferences, folder, AnalysisPlanPreferences(families=("between_groups",)))
    else:
        from Tools.LORETA_Visualizer.source_producers.source_validation_report import _write_text
        target = folder / "report.md"
        operation = partial(_write_text, target, "published\n")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_suffix(target.suffix + ".tmp")
    victim, before = _plant_staging_link(tmp_path, staging, kind)

    operation()

    assert victim.read_bytes() == before
    assert staging.read_bytes() == before
    assert target.is_file() and not target.is_symlink()
    assert set(target.parent.iterdir()) == {target, staging}


@pytest.mark.parametrize("failure", ["write", "fsync", "replace"])
def test_atomic_write_failure_keeps_prior_destination_and_cleans_staging(tmp_path, monkeypatch, failure):
    from Main_App.io import atomic_write as module
    target = tmp_path / "result.json"
    before = b'{"preserved": true}'
    target.write_bytes(before)

    def fail(*_args):
        raise OSError("injected publication failure")

    if failure != "write":
        monkeypatch.setattr(module.os, failure, fail)
    with pytest.raises(OSError, match="injected"):
        with module.atomic_write(target) as stream:
            stream.write('{"partial":')
            if failure == "write":
                fail()
            stream.write('true}')
    assert target.read_bytes() == before
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("kind", ["hardlink", "symlink"])
def test_run_log_rejects_linked_outside_file(tmp_path, kind):
    from Main_App.processing.processing_ledger import append_run_log, runs_path
    root = tmp_path / "project"
    target = runs_path(root)
    target.parent.mkdir(parents=True)
    victim, before = _plant_staging_link(tmp_path, target, kind)
    with pytest.raises(OSError, match="linked|regular"):
        append_run_log(root, {"status": "completed"})
    assert victim.read_bytes() == before


def test_run_log_preserves_prior_entries(tmp_path):
    from Main_App.processing.processing_ledger import append_run_log, runs_path
    append_run_log(tmp_path, {"status": "first"})
    append_run_log(tmp_path, {"status": "second"})
    records = [json.loads(line) for line in runs_path(tmp_path).read_text(encoding="utf-8").splitlines()]
    assert [record["status"] for record in records] == ["first", "second"]
    assert all(record["timestamp"] for record in records)


@pytest.mark.parametrize("operation", ["ledger", "run_log"])
def test_processing_state_writes_reject_windows_reparse_directory(tmp_path, monkeypatch, operation):
    from types import SimpleNamespace
    from Main_App.processing import processing_ledger as ledger
    root = tmp_path / "project"
    state = ledger.processing_state_dir(root)
    state.mkdir(parents=True)
    original = Path.lstat

    def reparse_info(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == state:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info

    monkeypatch.setattr(Path, "lstat", reparse_info)
    with pytest.raises(OSError, match="redirected"):
        if operation == "ledger":
            ledger.save_ledger(root, {"entries": {}})
        else:
            ledger.append_run_log(root, {"status": "completed"})
    assert list(state.iterdir()) == []
