from Tools.LORETA_Visualizer.method_info import LORETA_METHOD_INFO, LORETA_METHOD_INFO_HTML


def test_loreta_method_info_copy_covers_mask_and_references() -> None:
    html = LORETA_METHOD_INFO_HTML

    assert "Cluster-Based Permutation Mask" in html
    assert "eLORETA volume view is included as a visual estimate" in html
    assert "fsaverage template" in html
    assert "https://doi.org/10.1016/j.neuroimage.2021.118460" in html
    assert "https://doi.org/10.1016/j.neuroimage.2022.119177" in html
    assert "https://doi.org/10.1162/imag_a_00414" in html
    assert "https://mne.tools/stable/generated/mne.datasets.fetch_fsaverage.html" in html
    assert LORETA_METHOD_INFO.key == "loreta_method"
    assert LORETA_METHOD_INFO.title == "About LORETA Source Maps"
    assert LORETA_METHOD_INFO.html is LORETA_METHOD_INFO_HTML
