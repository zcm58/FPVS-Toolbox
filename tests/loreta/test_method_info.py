from Tools.LORETA_Visualizer.method_info import LORETA_METHOD_INFO, LORETA_METHOD_INFO_HTML


def test_loreta_method_info_copy_covers_mask_and_references() -> None:
    html = LORETA_METHOD_INFO_HTML
    normalized_html = " ".join(html.split())

    assert "Cluster-Based Permutation Mask" in html
    assert "generates both EEG-only L2-MNE cortical and" in normalized_html
    assert (
        "Each participant contributes to every canonical condition they completed"
        in normalized_html
    )
    assert (
        "A missing condition omits only that participant-condition input"
        in normalized_html
    )
    assert (
        "Every group-condition map records its own participant count and participant identities"
        in normalized_html
    )
    assert "complete-case participant cohort" not in normalized_html
    assert "l2_mne_hauk_source_psd_cortical_normal_v1" in html
    assert 'pick_ori="normal"' in html
    assert "l2_mne_hauk_source_psd_v1" in html
    assert "eloreta_volume_hauk_source_psd_vector_norm_v1" in html
    assert 'pick_ori="vector"' in html
    assert "sqrt(sum(abs(Cxyz)^2))" in html
    assert "never reuses the L2-MNE source arrays as eLORETA values" in normalized_html
    assert "does not fall back to FullFFT amplitude workbooks" in normalized_html
    assert "without reprocessing the EEG" in normalized_html
    assert "eloreta_volume_hauk_source_psd_v1" in html
    assert "basis-dependent" in html
    assert "Hauk-informed Toolbox extension" in normalized_html
    assert "fsaverage template" in normalized_html
    assert "Both methods are EEG-only" in normalized_html
    assert "https://doi.org/10.1016/j.neuroimage.2021.118460" in html
    assert "https://doi.org/10.1016/j.neuroimage.2022.119177" in html
    assert "https://doi.org/10.1162/imag_a_00414" in html
    assert "https://mne.tools/stable/generated/mne.datasets.fetch_fsaverage.html" in html
    assert LORETA_METHOD_INFO.key == "loreta_method"
    assert LORETA_METHOD_INFO.title == "About LORETA Source Maps"
    assert LORETA_METHOD_INFO.html is LORETA_METHOD_INFO_HTML
