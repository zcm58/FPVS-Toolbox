from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from Tools.LORETA_Visualizer.prepared_payload_validator import validate_prepared_source_payload_json
from Tools.LORETA_Visualizer.source_producers.contracts import ProducedPayload
from Tools.LORETA_Visualizer.source_producers.source_validation_report import write_project_source_validation_report


@pytest.mark.parametrize("metadata", [{}, {"source_validity": None}], ids=["omitted", "null"])
def test_report_accepts_validated_finite_historical_payload_without_validity(tmp_path, metadata):
    payload_path = tmp_path / "historical.json"
    raw_payload = {
        "format": "fpvs-loreta-source-payload-v1",
        "coordinate_space": "mni", "kind": "surface_points",
        "points": [[0, 0, 0], [1, 0, 0]], "values": [1.5, 2.5],
        "metadata": metadata,
    }
    payload_path.write_text(json.dumps(raw_payload), encoding="utf-8")
    payload = ProducedPayload(
        "condition", "Condition", payload_path, validate_prepared_source_payload_json(payload_path),
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "format": "fpvs-loreta-source-manifest-v1",
        "conditions": [{"id": "condition", "label": "Condition", "file": payload_path.name}],
    }), encoding="utf-8")

    result = write_project_source_validation_report(
        output_dir=tmp_path, manifest_path=manifest_path, payloads=(payload,),
        project_inputs=SimpleNamespace(project_root=tmp_path, conditions=("condition",)),
        export_model="historical",
    )

    report = json.loads(result.json_path.read_text(encoding="utf-8"))
    summary = report["payload_summaries"][0]
    assert summary["source_validity"] == {"policy": "historical_undeclared"}
    assert (summary["value_min"], summary["value_max"]) == (1.5, 2.5)
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "## Payload Summary" in markdown
    assert "Valid sources" in markdown
    assert payload_path.name in markdown
    assert json.loads(payload_path.read_text(encoding="utf-8")) == raw_payload
