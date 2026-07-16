from Tools.LORETA_Visualizer.method_info import LORETA_METHOD_INFO, LORETA_METHOD_INFO_HTML


def test_loreta_method_info_copy_covers_mask_and_references() -> None:
    html = LORETA_METHOD_INFO_HTML

    assert "Cluster-Based Permutation Mask" in html
    assert "generates both EEG-only L2-MNE cortical and" in html
    assert "same complete-case participant cohort" in html
    assert "never reuses the L2-MNE source arrays as eLORETA values" in html
    assert "does not fall back to FullFFT amplitude workbooks" in html
    assert "amplitude-derived eLORETA manifests remain importable" in html
    assert "legacy/exploratory workflows" in html
    assert "Hauk-informed extensions" in html
    assert "fsaverage template" in html
    assert "Both methods are EEG-only" in html
    assert "https://doi.org/10.1016/j.neuroimage.2021.118460" in html
    assert "https://doi.org/10.1016/j.neuroimage.2022.119177" in html
    assert "https://doi.org/10.1162/imag_a_00414" in html
    assert "https://mne.tools/stable/generated/mne.datasets.fetch_fsaverage.html" in html
    assert LORETA_METHOD_INFO.key == "loreta_method"
    assert LORETA_METHOD_INFO.title == "About LORETA Source Maps"
    assert LORETA_METHOD_INFO.html is LORETA_METHOD_INFO_HTML
