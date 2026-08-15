from __future__ import annotations

from Tools.Free_Harmonic_Clustering.tool_info import (
    FREE_HARMONIC_CLUSTERING_TOOL_INFO,
    METHOD_HTML,
    OVERVIEW_HTML,
)


def test_method_tab_owns_locked_profile_guidance() -> None:
    tabs = {tab.key: tab for tab in FREE_HARMONIC_CLUSTERING_TOOL_INFO.tabs}

    assert tabs["method"].title == "Method"
    assert tabs["method"].html == METHOD_HTML
    method_copy = METHOD_HTML.casefold()
    assert "locked, read-only" in method_copy
    assert "10,000" in method_copy
    assert "z &gt; 3.29" in method_copy
    assert "sign-specific cluster p-values" in method_copy
    assert "&le; .025" in method_copy
    assert "l2 normalization" in method_copy
    assert "deterministic, recorded random seed" in method_copy
    assert "swap a/b" not in OVERVIEW_HTML.casefold()
