import pytest

try:
    from Main_App.PySide6_App.workers.processing_worker import PostProcessWorker
    import Main_App.PySide6_App.workers.processing_worker as worker_module
except Exception:  # pragma: no cover - environment guard
    pytest.skip("PySide6 not available", allow_module_level=True)



def test_postprocess_worker_reports_generated_excel_paths(tmp_path, monkeypatch):
    output_root = tmp_path / "1 - Excel Data Files"
    output_root.mkdir()

    def _fake_export(ctx, labels):
        (output_root / "P01_results.xlsx").write_text("ok", encoding="utf-8")

    monkeypatch.setattr(worker_module, "run_post_export", _fake_export)

    payloads = []
    worker = PostProcessWorker(
        file_name="demo.bdf",
        epochs_dict={"A": object()},
        labels=["A"],
        save_folder=output_root,
        data_paths=["demo.bdf"],
        settings=None,
    )
    worker.finished.connect(payloads.append)

    worker.run()

    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["generated_excel_paths"] == [str((output_root / "P01_results.xlsx").resolve())]
    assert payload["existing_excel_paths"] == [str((output_root / "P01_results.xlsx").resolve())]


def test_postprocess_worker_accepts_overwrite_only_runs(tmp_path, monkeypatch):
    output_root = tmp_path / "1 - Excel Data Files"
    output_root.mkdir()
    existing = output_root / "P01_results.xlsx"
    existing.write_text("old", encoding="utf-8")

    def _fake_export(ctx, labels):
        existing.write_text("new", encoding="utf-8")

    monkeypatch.setattr(worker_module, "run_post_export", _fake_export)

    payloads = []
    worker = PostProcessWorker(
        file_name="demo.bdf",
        epochs_dict={"A": object()},
        labels=["A"],
        save_folder=output_root,
        data_paths=["demo.bdf"],
        settings=None,
    )
    worker.finished.connect(payloads.append)

    worker.run()

    payload = payloads[0]
    assert payload["generated_excel_paths"] in ([str(existing.resolve())], [])
    assert payload["existing_excel_paths"] == [str(existing.resolve())]
