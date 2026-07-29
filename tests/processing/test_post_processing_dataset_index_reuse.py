from __future__ import annotations

from types import SimpleNamespace

import pytest

from Main_App.processing.frequency_domain_qc import run_frequency_domain_qc_review
from Main_App.processing.harmonic_selection_qc import (
    run_processing_harmonic_selection_qc,
)
from Tools.LORETA_Visualizer.stats_ready_workbook import (
    write_loreta_stats_ready_workbook,
)


def test_post_processing_entry_points_reject_dataset_index_from_other_project(
    tmp_path,
) -> None:
    project = SimpleNamespace(project_root=tmp_path)
    wrong_index = SimpleNamespace(project_root=tmp_path / "Different Project")

    with pytest.raises(ValueError, match="different project root"):
        run_frequency_domain_qc_review(project, dataset_index=wrong_index)
    with pytest.raises(ValueError, match="different project root"):
        run_processing_harmonic_selection_qc(project, dataset_index=wrong_index)
    with pytest.raises(ValueError, match="different project root"):
        write_loreta_stats_ready_workbook(tmp_path, dataset_index=wrong_index)
