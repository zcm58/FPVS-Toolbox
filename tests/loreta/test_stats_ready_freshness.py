from __future__ import annotations

import json
from pathlib import Path

from Main_App.processing.artifact_freshness import (
    STATS_READY_SUMMED_BCA_ARTIFACT,
    activate_selection_freshness,
    mark_artifact_current,
    mark_selection_derivatives_stale,
)
from Tools.LORETA_Visualizer.stats_ready_workbook import (
    default_loreta_stats_ready_workbook_path,
    stats_ready_workbook_exists,
)


def test_managed_stats_ready_exists_only_while_freshness_is_current(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "project.json").write_text(
        json.dumps({"schema_version": "2.1.0"}),
        encoding="utf-8",
    )
    summary = project_root / "Quality Check" / "Harmonic_Selection_Summary.xlsx"
    summary.parent.mkdir(parents=True)
    summary.write_text("selection", encoding="utf-8")
    workbook = default_loreta_stats_ready_workbook_path(project_root)
    workbook.parent.mkdir(parents=True)
    workbook.write_text("workbook", encoding="utf-8")

    assert stats_ready_workbook_exists(project_root) is False

    activate_selection_freshness(
        project_root,
        {"selection_fingerprint": "active"},
        selection_summary_path=summary,
    )
    mark_artifact_current(
        project_root,
        STATS_READY_SUMMED_BCA_ARTIFACT,
        workbook,
        "active",
    )

    assert stats_ready_workbook_exists(project_root) is True

    mark_selection_derivatives_stale(
        project_root,
        reason="Harmonic-selection settings changed.",
    )

    assert workbook.is_file()
    assert stats_ready_workbook_exists(project_root) is False
