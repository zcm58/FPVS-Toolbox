from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon

from Main_App.gui.icons import _SIDEBAR_ICON_PATHS, sidebar_icon


EXPECTED_SIDEBAR_ICONS = {
    "home",
    "stats",
    "harmonic",
    "sensitivity",
    "chart",
    "scalp",
    "loreta",
    "sequence",
    "ratio",
    "detectability",
    "settings",
    "info",
    "help",
}


def test_sidebar_icon_set_has_a_vector_definition_for_every_navigation_item() -> None:
    assert EXPECTED_SIDEBAR_ICONS <= _SIDEBAR_ICON_PATHS.keys()
    assert all("<" in _SIDEBAR_ICON_PATHS[kind] for kind in EXPECTED_SIDEBAR_ICONS)


def test_sidebar_icons_use_the_vector_icon_engine(qtbot) -> None:
    for kind in EXPECTED_SIDEBAR_ICONS:
        icon = sidebar_icon(kind)
        assert not icon.isNull()
        assert icon.cacheKey() == sidebar_icon(kind).cacheKey()

    high_dpi = sidebar_icon("home").pixmap(
        QSize(20, 20),
        2.0,
        QIcon.Normal,
        QIcon.Off,
    )
    assert high_dpi.devicePixelRatio() == 2.0
    assert high_dpi.width() == 40
    assert high_dpi.height() == 40
