"""Qualify released cap geometry, cohort layouts and map inputs with native MNE positions."""

from dataclasses import replace
import json
from types import SimpleNamespace

import mne
import numpy as np
import pandas as pd
import pytest

from Main_App.io.acticap_montages import make_acticap_montage
from Main_App.io.recorded_eeg_geometry import attach_raw_recorded_geometry
from Main_App.processing import roi_coverage
from Main_App.processing.recorded_cohort_geometry import recorded_cohort_geometry_identity
from Main_App.processing.recorded_scalp_identity import RecordedScalpIdentity
from Tools.Publication_Maps import metrics
from Tools.Publication_Maps.display_montage import DisplayMontage, load_display_montage
from Tools.Publication_Maps.models import PublicationMapInputError, PublicationMapRequest
from Tools.Publication_Maps.scalp_io import align_render_values, recorded_map_geometry, require_compatible_geometry


def _raw(names):
    info = mne.create_info(names, sfreq=250, ch_types="eeg")
    return mne.io.RawArray(np.zeros((len(names), 1)), info, verbose=False)


@pytest.mark.parametrize(("platform", "cap", "template", "count"), [
    ("biosemi_active_three", "biosemi128", "biosemi128", 128),
    ("brain_products", "brainproducts_acticap_gacs_64", "brainproducts_acticap_gacs_64", 64),
    ("brain_products", "brainproducts_acticap_gacs_128", "brainproducts_acticap_gacs_128", 128),
    ("unicorn", "unicorn8", "standard_1020", 8),
    ("brain_products", "GSN-HydroCel-129", "GSN-HydroCel-129", 129),
])
def test_explicit_template_keeps_every_source_location_and_signal_policy(platform, cap, template, count):
    if platform == "unicorn":
        names = ["Fz", "C3", "Cz", "C4", "Pz", "PO7", "Oz", "PO8"]
    elif "acticap" in cap:
        names = make_acticap_montage(cap).ch_names
    else:
        names = mne.channels.make_standard_montage(template).ch_names
    raw = _raw(names)
    source = attach_raw_recorded_geometry(
        raw, montage_id=cap, template_montage=template, hardware_platform=platform,
        interpolation_allowed=platform != "unicorn",
    )
    geometry = recorded_map_geometry(source, source_id="R1")
    rows = pd.DataFrame({"electrode": names[::-1], "render_value": np.arange(count)[::-1]})
    data, info, missing, _ = align_render_values(rows, geometry=geometry)
    assert missing == 0 and len(data) == count
    assert source["interpolation_supported"] is (platform != "unicorn")
    for channel, value in zip(info["chs"], data, strict=True):
        assert value == names.index(channel["ch_name"])
        np.testing.assert_array_equal(channel["loc"][:3], source["channel_coordinates_m"][channel["ch_name"]])


_XYZ = {"A": (-.06, .04, .07), "B": (.07, .04, .08), "C": (-.04, -.07, .09),
        "D": (.04, -.08, .08), "E": (0, .01, .14)}


def _measured(shift=0., *, missing=False):
    raw = _raw(list(_XYZ))
    if not missing:
        xyz = {name: np.array(pos) + (shift, 0, 0) for name, pos in _XYZ.items()}
        raw.set_montage(mne.channels.make_dig_montage(ch_pos=xyz, coord_frame="head"))
    return attach_raw_recorded_geometry(raw)


def test_measured_cohort_layout_gives_each_recording_one_vote_and_retains_full_dig():
    a = recorded_map_geometry(_measured(), source_id="P01-visit1")
    b = recorded_map_geometry(_measured(.004), source_id="P01-visit2")
    pooled = require_compatible_geometry((a, a, require_compatible_geometry((a, b))))
    assert pooled == require_compatible_geometry((b, a))
    assert len(pooled.source_positions) == 2
    rows = pd.DataFrame({"electrode": list(_XYZ), "render_value": [2, 3, 4, 5, np.nan]})
    values, info, missing, _ = align_render_values(rows, geometry=pooled)
    assert missing == 1 and list(values) == [2, 3, 4, 5]
    assert len(info["dig"]) >= len(_XYZ)
    for channel in info["chs"]:
        xyz = channel["loc"][:3]
        np.testing.assert_allclose(xyz, np.array(_XYZ[channel["ch_name"]]) + (.002, 0, 0))
    with pytest.raises(PublicationMapInputError, match="Conflicting"):
        require_compatible_geometry((a, recorded_map_geometry(_measured(.004), source_id="p01-visit1")))
    with pytest.raises(PublicationMapInputError, match="incompatible"):
        require_compatible_geometry((a, replace(b, montage_id="Other cap")))
    with pytest.raises(PublicationMapInputError, match="incompatible"):
        require_compatible_geometry((a, None))


def test_coordinate_free_recording_requires_a_complete_named_fallback():
    unavailable = _measured(missing=True)
    with pytest.raises(PublicationMapInputError, match="lacks complete electrode positions"):
        recorded_map_geometry(unavailable, source_id="R1")
    matching = DisplayMontage("Laboratory cap", tuple(_XYZ.items()))
    qualified = recorded_map_geometry(unavailable, source_id="R1", display_montage=matching)
    assert qualified.coordinate_source == "display_template:Laboratory cap"
    incomplete = DisplayMontage("Omitted E", tuple(_XYZ.items())[:-1])
    with pytest.raises(PublicationMapInputError, match="no position.*E"):
        recorded_map_geometry(unavailable, source_id="R1", display_montage=incomplete)
    assert recorded_map_geometry(_measured(), source_id="R1", display_montage=incomplete).coordinate_source == "recording"
    tampered = dict(unavailable, coordinate_frame="head")
    with pytest.raises(ValueError, match="inconsistent"):
        recorded_map_geometry(tampered, source_id="R1", display_montage=matching)


def test_distinct_recorded_labels_cannot_silently_share_one_template_site():
    template = load_display_montage("standard_1020")
    for left_temporal in ("T7", "T3"):
        raw = _raw([left_temporal, "Cz", "O1", "O2"])
        geometry = recorded_map_geometry(attach_raw_recorded_geometry(raw), source_id="R1", display_montage=template)
        assert left_temporal in geometry.channel_names
    raw = _raw(["T7", "T3", "Cz", "O1", "O2"])
    with pytest.raises(PublicationMapInputError, match="'T3' and 'T7' at the same head position"):
        recorded_map_geometry(attach_raw_recorded_geometry(raw), source_id="R1", display_montage=template)


def test_managed_selected_workbooks_resolve_each_measured_source_from_cohort_evidence(tmp_path, monkeypatch):
    ids = ("P01", "P02")
    cohort = recorded_cohort_geometry_identity(
        {ids[0]: _measured(), ids[1]: _measured(.004)}, source_identity_kind="participant_id",
        processing_identity={"processing_fingerprint_version": "test", "processing_fingerprint": "same"},
    )
    retained = RecordedScalpIdentity.from_geometry(cohort)
    (tmp_path / "project.json").write_text(json.dumps({
        "schema_version": "2.1.0", "subfolders": {"excel": "Excel"}, "groups": {},
        "participants": {who: {} for who in ids}, "preprocessing": {},
    }), encoding="utf-8")
    excel = tmp_path / "Excel"
    folder = excel / "Faces"
    folder.mkdir(parents=True)
    cells = []
    for i, who in enumerate(ids):
        path = folder / f"{who}_Faces_Results.xlsx"
        rows = pd.DataFrame({"Electrode": [*_XYZ, "REF"], "1.2000_Hz": [i + 1] * 5 + [90]})
        rows.to_excel(path, sheet_name="BCA (uV)", index=False)
        evidence = roi_coverage.validate_roi_source_rows(
            rows, retained_scalp=retained, allowed_auxiliary_rows=("REF",), required_columns=("1.2000_Hz",),
        )
        cells.append(SimpleNamespace(
            workbook_path=str(path), participant_id=who, recording_id=who, source_evidence=evidence,
        ))
    monkeypatch.setattr(roi_coverage, "require_project_final_release", lambda _: (
        object(), SimpleNamespace(cells=cells, fingerprint="coverage"), SimpleNamespace(fingerprint="release"),
    ))
    monkeypatch.setattr(metrics, "_select_stats_significant_harmonics", lambda **_: ((1.2,), {}))
    request = PublicationMapRequest(input_root=excel, output_root=tmp_path / "figures", project_root=tmp_path,
                                    conditions=("Faces",))
    result = metrics.build_publication_map_result(request)
    assert result.selection_metadata["scalp_map_geometry_recordings"] == ["p01", "p02"]
    values = result.grand_average_values
    assert not values.loc[values.electrode == "REF", "is_montage_electrode"].any()
    data, info, missing, _ = align_render_values(values, geometry=result.geometry)
    assert info.ch_names == list(_XYZ) and missing == 0
    np.testing.assert_array_equal(data, [1.5] * 5)
    with pytest.raises(PublicationMapInputError, match="requires the active project root"):
        metrics.build_publication_map_result(replace(request, project_root=None))
    cells[0].participant_id = "Unrelated"
    with pytest.raises(PublicationMapInputError, match="no electrode geometry for 'Unrelated'"):
        metrics.build_publication_map_result(request)


@pytest.mark.parametrize("missing", [True, False])
def test_multi_group_worker_snapshots_fallback_only_if_needed(tmp_path, monkeypatch, missing):
    from Tools.Publication_Maps import display_montage, scalp_scene, worker
    from Tools.Publication_Maps.models import PublicationMapResult
    from Tools.Publication_Maps.generation_outcome import PublicationMapsOutcomeStatus

    identity = RecordedScalpIdentity.from_geometry(_measured(missing=missing))
    source = metrics._ReleasedPublicationSource(
        workbook_path=tmp_path / "source", retained_scalp_channels=identity.channels,
        allowed_auxiliary_rows=(), observed_auxiliary_rows=(), source_evidence_fingerprint="frozen",
        recorded_identity=identity, recording_id="R1", participant_id="P01",
    )
    selected_file = tmp_path / "montage.csv"
    layout = DisplayMontage("Bench", tuple(_XYZ.items()))
    reads = []
    def read_selected(path):
        assert path == selected_file and not reads
        reads.append(path)
        return layout

    def build_result(request, *, load_fallback, cancel_check):
        geometry = metrics._released_geometry([source, source], request, load_fallback=load_fallback)
        return PublicationMapResult(pd.DataFrame(), pd.DataFrame(), geometry=geometry)

    monkeypatch.setattr(display_montage, "load_display_montage", read_selected)
    monkeypatch.setattr(worker, "build_publication_map_result", build_result)
    monkeypatch.setattr(scalp_scene, "build_surface_panels", lambda *args, **kwargs: ())
    requests = [PublicationMapRequest(
        input_root=tmp_path / "Excel", output_root=tmp_path / "Output", conditions=("Shapes",),
        group_id=group, group_folder=group, scalp_view="3d", display_montage=selected_file,
    ) for group in ("Clinical", "Control")]
    batch = worker.PublicationMapsWorker(requests, preview_only=True)
    batch.run()
    assert batch.outcome.status is PublicationMapsOutcomeStatus.SUCCESS, batch.outcome.message
    assert reads == ([selected_file] if missing else [])
