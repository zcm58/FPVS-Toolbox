from Main_App.gui.processing_workflows import _post_processing_display_state


def test_post_processing_perf_progress_is_user_facing_harmonic_text() -> None:
    title, message = _post_processing_display_state(
        "[PERF] Group policy BCA aggregation progress: 10/126 workbooks "
        "(participant=P10, condition=Neutral Happy, last_read=0.02s, elapsed=0.22s)."
    )

    assert title == "Identifying Significant Harmonics"
    assert message == "FPVS Toolbox is currently identifying significant harmonics."
    assert "[PERF]" not in message


def test_post_processing_fullfft_source_progress_is_user_facing_source_map_text() -> None:
    title, message = _post_processing_display_state(
        "Reading participant FullFFT workbooks and selected harmonics..."
    )

    assert title == "Generating Source Maps"
    assert message == "Generating source-space maps for 3D visualization of oddball responses."
