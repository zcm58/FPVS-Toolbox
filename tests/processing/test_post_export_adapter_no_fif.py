import Main_App.exports.post_export_adapter as adapter
from Main_App.exports.post_export_adapter import LegacyCtx, run_post_export


class _EpochsThatMustNotSave:
    def save(self, *_args, **_kwargs):
        raise AssertionError("Unexpected FIF save attempt")


def test_run_post_export_ignores_legacy_fif_flag(tmp_path, monkeypatch):
    save_root = tmp_path / "1 - Excel Data Files"
    save_root.mkdir()

    called = {}

    def _fake_shared_post_process(shim, labels):
        called["labels"] = labels
        called["save_fif_var"] = shim.save_fif_var.get()
        called["save_condition_fif"] = shim.save_condition_fif
        (save_root / "P01_results.xlsx").write_text("ok", encoding="utf-8")

    monkeypatch.setattr(adapter, "_shared_post_process", _fake_shared_post_process)

    ctx = LegacyCtx(
        preprocessed_data={"CondA": [_EpochsThatMustNotSave()]},
        save_folder_path=save_root,
        data_paths=["sample.bdf"],
        settings={"save_preprocessed_fif": True},
    )

    written = run_post_export(ctx, ["CondA"])

    assert written == 0
    assert called["labels"] == ["CondA"]
    assert called["save_fif_var"] is False
    assert called["save_condition_fif"] is False
    assert not (save_root / ".fif files").exists()
    assert (save_root / "P01_results.xlsx").exists()
