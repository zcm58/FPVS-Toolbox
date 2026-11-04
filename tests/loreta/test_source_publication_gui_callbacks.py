"""Exercise actual GUI callback bodies without importing or starting Qt."""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace


GUI_PATH = Path(__file__).resolve().parents[2] / "src/Tools/LORETA_Visualizer/gui.py"


@dataclass
class _Batch:
    results: tuple
    failures: tuple


def _method(name, *, class_name="LoretaVisualizerWindow", extra_globals=None):
    tree = ast.parse(GUI_PATH.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
    method.decorator_list = []
    namespace = {
        "Path": Path, "SourcePayload": object, "logger": logging.getLogger(__name__),
        "ProjectSourceMapExportBatchResult": _Batch,
        "PROJECT_ZSCORE_MODEL_PARTICIPANT_FIRST": "participant_first",
        "SOURCE_METHOD_L2_MNE_SOURCE_PSD": "l2", "SOURCE_METHOD_ELORETA_VOLUME_SOURCE_PSD": "eloreta",
        "SOURCE_METHOD_L2_MNE_SURFACE": "legacy_l2", "SOURCE_METHOD_ELORETA_VOLUME": "legacy_eloreta",
        "PROJECT_SOURCE_EXPORT_DEFAULT_MODES": ("l2", "eloreta"),
        "_source_export_mode_label": str,
    }
    namespace.update(extra_globals or {})
    module = ast.Module(body=[method], type_ignores=[])
    exec(compile(module, str(GUI_PATH), "exec"), namespace)
    return namespace[name]


def test_partial_success_imports_only_returned_manifest_and_retains_warning(tmp_path):
    old = tmp_path / "old_volume" / "manifest.json"
    old.parent.mkdir()
    old.write_text("{}")
    new = tmp_path / "new_l2" / "manifest.json"
    new.parent.mkdir()
    new.write_text("{}")
    imports, statuses = [], []
    window = SimpleNamespace(
        _include_flagged_subjects=True, _selected_source_method_id="l2",
        _set_source_export_status=lambda text, *, variant: statuses.append((text, variant)),
        _import_prepared_source_manifests=lambda paths, **kwargs: imports.append(paths),
    )
    result = SimpleNamespace(
        output_dir=new.parent, manifest_path=new,
        producer_result=SimpleNamespace(method_id="l2_mne_hauk_source_psd_v1", payloads=(object(),)),
    )
    _method("_on_project_source_maps_exported")(
        window, _Batch((result,), (SimpleNamespace(export_mode="eLORETA"),))
    )
    assert imports == [(new,)]
    assert old.is_file()
    assert "eLORETA failed" in window._source_build_warning
    assert statuses[-1][1] == "warning"
    _method("_set_payload_display_status")(window, object())
    assert statuses[-1] == (window._source_build_warning, "warning")


def test_obsolete_discovery_cannot_replace_newly_requested_maps(tmp_path):
    imports = []
    window = SimpleNamespace(
        _closing_requested=False, _source_discovery_request_id=2,
        _refresh_project_root=lambda: tmp_path,
        _import_prepared_source_manifests=lambda *args, **kwargs: imports.append(args),
    )
    _method("_on_project_source_discovery_completed")(
        window, ((tmp_path, True, False, 1), (tmp_path / "obsolete.json",))
    )
    assert imports == []


def test_current_discovery_invalidates_project_maps_if_no_bundle_is_current(tmp_path):
    invalidations = []
    window = SimpleNamespace(
        _closing_requested=False, _source_discovery_request_id=2,
        _refresh_project_root=lambda: tmp_path,
        _invalidate_project_source_maps_after_pipeline=invalidations.append,
    )
    _method("_on_project_source_discovery_completed")(window, ((tmp_path, False, True, 2), ()))
    assert invalidations == [tmp_path]


def test_discovery_failure_emits_actionable_status_and_always_finishes(tmp_path):
    request = (tmp_path, False, False, 1)
    failures, finished, discovered, statuses = [], [], [], []
    def fail(_root):
        raise OSError("Source receipt cannot be read")
    worker = SimpleNamespace(
        _request=request, failed=SimpleNamespace(emit=failures.append),
        discovered=SimpleNamespace(emit=discovered.append),
        finished=SimpleNamespace(emit=lambda: finished.append(True)),
    )
    _method("run", class_name="ProjectSourceDiscoveryWorker", extra_globals={
        "default_project_source_manifest_paths": fail,
    })(worker)
    assert discovered == []
    assert failures == [(request, "Source receipt cannot be read")]
    assert finished == [True]
    window = SimpleNamespace(
        _closing_requested=False, _source_discovery_request_id=1,
        _refresh_project_root=lambda: tmp_path,
        _set_source_export_status=lambda message, *, variant: statuses.append((message, variant)),
    )
    _method("_on_project_source_discovery_failed")(window, failures[0])
    assert statuses == [("Cannot verify project source maps: Source receipt cannot be read", "warning")]
