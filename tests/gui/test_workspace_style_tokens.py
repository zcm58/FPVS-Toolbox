from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QColor

from Main_App.gui import icons, theme
from Main_App.gui.menu_bar import BETA_TOOL_SPECS
from Main_App.gui.style_tokens import (
    ACCENT_COLOR,
    ACCENT_COLOR_HOVER,
    ACCENT_COLOR_PRESSED,
    ACCENT_SOFT_BG,
    CHROME_ACTIVE,
    CHROME_MUTED_TEXT,
    CHROME_TEXT,
    CONTROL_BORDER,
    DANGER_COLOR,
    DANGER_SOFT_BG,
    FOCUS_COLOR,
    HEADER_BG,
    INFO_BG,
    ON_ACTION,
    PAGE_BG,
    PROGRESS_FILL,
    SIGNAL_COLOR,
    SUCCESS_SOFT_BG,
    SURFACE_BG,
    TEXT_MUTED,
    TEXT_PRIMARY,
    WARNING_SOFT_BG,
    build_workspace_chrome_stylesheet,
    render_ui_stylesheet,
    resolve_ui_color,
)


@pytest.mark.parametrize("frozen", [False, True])
def test_application_icon_loads_from_checkout_or_bundle_independent_of_cwd(tmp_path, monkeypatch, frozen) -> None:
    asset = Path(__file__).resolve().parents[2] / "assets" / "experiment_library" / "wave.svg"
    runtime = SimpleNamespace(frozen=frozen)
    if frozen:
        runtime._MEIPASS = str(tmp_path / "bundle")
        bundled_asset = Path(runtime._MEIPASS) / "assets" / "experiment_library" / asset.name
        bundled_asset.parent.mkdir(parents=True)
        bundled_asset.write_bytes(asset.read_bytes())
        asset = bundled_asset

    def file_icon(filename):
        path = Path(filename)
        return SimpleNamespace(path=path, isNull=lambda: not path.is_file())

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(icons, "sys", runtime)
    monkeypatch.setattr(icons, "QIcon", file_icon)
    assert icons.application_icon().path == asset


def test_missing_bundled_application_icon_fails_explicitly(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(icons, "sys", SimpleNamespace(frozen=True, _MEIPASS=str(tmp_path)))
    monkeypatch.setattr(icons, "QIcon", lambda _filename: SimpleNamespace(isNull=lambda: True))
    with pytest.raises(RuntimeError, match="Cannot load the FPVS Toolbox application icon"):
        icons.application_icon()


def test_beta_tool_inventory_and_routes_match_supported_surfaces() -> None:
    assert BETA_TOOL_SPECS == (
        ("btn_publication_maps", "Scalp Maps", "open_publication_maps"),
        ("btn_data", "Standard FPVS Screening", "open_stats_analyzer"),
        ("btn_sensitivity_analysis", "Sensitivity Analysis", "open_sensitivity_analysis"),
        ("btn_loreta_visualizer", "LORETA Visualizer", "open_loreta_visualizer"),
        ("btn_sequence_figure", "Sequence Figure", "open_sequence_figure"),
        ("btn_individual_detectability", "Individual Detectability", "open_individual_detectability"),
    )


def _stylesheet_rules(stylesheet: str) -> dict[str, dict[str, str]]:
    rules = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]+)\}", stylesheet):
        declarations = dict(re.findall(r"([\w-]+)\s*:\s*([^;]+);", body))
        for selector in selectors.split(","):
            rules.setdefault(selector.strip(), {}).update(declarations)
    return rules


def test_menu_feedback_is_owned_by_the_native_style() -> None:
    for stylesheet in (build_workspace_chrome_stylesheet(), theme.build_fpvs_app_stylesheet()):
        rules = _stylesheet_rules(stylesheet)
        assert not any(selector.startswith(("QMenuBar", "QMenu")) for selector in rules)


def test_settings_navigation_uses_one_keyboard_focus_indicator() -> None:
    rules = _stylesheet_rules(theme.build_fpvs_app_stylesheet())
    assert rules["QListWidget#settings_navigation"]["outline"] == "none"
    assert rules["QListWidget#settings_navigation::item:focus"]["border-color"] == FOCUS_COLOR
    assert rules["QLineEdit"]["border"] == f"1px solid {CONTROL_BORDER}"
    assert rules["QLineEdit"]["placeholder-text-color"] == TEXT_MUTED


def test_control_chevrons_are_resolved_independently_of_working_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    rules = _stylesheet_rules(theme.build_fpvs_app_stylesheet())
    assert rules["QComboBox::drop-down"]["border"] == "none"
    images = {
        "QComboBox::down-arrow": "chevron-down.svg",
        "QSpinBox::up-arrow": "chevron-up.svg",
        "QSpinBox::down-arrow": "chevron-down.svg",
        "QDoubleSpinBox::up-arrow": "chevron-up.svg",
        "QDoubleSpinBox::down-arrow": "chevron-down.svg",
    }
    for selector, filename in images.items():
        image = rules[selector]["image"]
        path = Path(image.removeprefix('url("').removesuffix('")'))
        assert path.is_absolute()
        assert path.name == filename
        assert path.is_file()


def test_local_stylesheet_translates_only_opt_in_interface_colors() -> None:
    stylesheet = (
        f'QWidget[selection="{SURFACE_BG}"] {{ background: {SURFACE_BG}; '
        f'border-color: {CONTROL_BORDER}; image: url("{SURFACE_BG}.svg"); '
        'selection-color: #2E8B57; background-color: white; color: white; }'
    )

    assert render_ui_stylesheet(stylesheet, dark=False) == stylesheet
    rendered = render_ui_stylesheet(stylesheet, dark=True)
    assert f'[selection="{SURFACE_BG}"]' in rendered
    assert f'url("{SURFACE_BG}.svg")' in rendered
    assert f"background: {resolve_ui_color(SURFACE_BG, dark=True)};" in rendered
    assert f"border-color: {resolve_ui_color(CONTROL_BORDER, dark=True)};" in rendered
    assert f"color: {resolve_ui_color(ON_ACTION, dark=True)};" in rendered
    assert "background-color: white;" in rendered
    assert "selection-color: #2E8B57;" in rendered


def test_dark_application_stylesheet_uses_bundled_dark_chevrons() -> None:
    rules = _stylesheet_rules(theme._render_stylesheet(theme.build_fpvs_app_stylesheet(), dark=True))
    for selector, direction in (("QComboBox::down-arrow", "down"), ("QSpinBox::up-arrow", "up")):
        filename = rules[selector]["image"].removeprefix('url("').removesuffix('")')
        path = Path(filename)
        assert path.name == f"chevron-{direction}-dark.svg"
        assert path.is_file()


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
def test_check_and_radio_indicators_use_compact_contrasting_states(dark: bool) -> None:
    rules = _stylesheet_rules(theme._render_stylesheet(theme.build_fpvs_app_stylesheet(), dark=dark))
    border = resolve_ui_color(CONTROL_BORDER, dark=dark)
    focus = resolve_ui_color(FOCUS_COLOR, dark=dark)
    for selector in ("QCheckBox::indicator", "QRadioButton::indicator"):
        assert rules[selector]["width"] == rules[selector]["height"] == "11px"
        assert rules[selector]["border"] == f"1px solid {border}"
        assert rules[f"{selector}:focus:enabled"]["border-color"] == focus
        assert rules[f"{selector}:checked:disabled"]["border-color"] == border

    image = rules["QCheckBox::indicator:checked"]["image"]
    path = Path(image.removeprefix('url("').removesuffix('")'))
    expected_stroke = QColor(resolve_ui_color(ON_ACTION, dark=dark))
    actual_stroke = re.search(r'stroke="([^"]+)"', path.read_text(encoding="utf-8"))
    assert actual_stroke is not None and QColor(actual_stroke.group(1)) == expected_stroke


def _luminance(color: str) -> float:
    rgba = QColor(color).getRgbF()
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in rgba[:3]
    ]
    return sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
def test_shared_appearance_text_and_control_contrast(dark: bool) -> None:
    pairs = (
        (TEXT_PRIMARY, PAGE_BG, 4.5),
        (TEXT_PRIMARY, SURFACE_BG, 4.5),
        (TEXT_MUTED, SURFACE_BG, 4.5),
        (ACCENT_COLOR, PAGE_BG, 4.5),
        (TEXT_PRIMARY, ACCENT_SOFT_BG, 4.5),
        (ON_ACTION, ACCENT_COLOR, 4.5),
        (ON_ACTION, ACCENT_COLOR_HOVER, 4.5),
        (ON_ACTION, ACCENT_COLOR_PRESSED, 4.5),
        (ON_ACTION, DANGER_COLOR, 4.5),
        (TEXT_PRIMARY, DANGER_SOFT_BG, 4.5),
        (TEXT_PRIMARY, SUCCESS_SOFT_BG, 4.5),
        (TEXT_PRIMARY, WARNING_SOFT_BG, 4.5),
        (TEXT_PRIMARY, INFO_BG, 4.5),
        (TEXT_PRIMARY, PROGRESS_FILL, 4.5),
        (CHROME_TEXT, HEADER_BG, 4.5),
        (CHROME_MUTED_TEXT, HEADER_BG, 4.5),
        (CONTROL_BORDER, SURFACE_BG, 3),
        (CONTROL_BORDER, PAGE_BG, 3),
        (ON_ACTION, CONTROL_BORDER, 3),
        (FOCUS_COLOR, SURFACE_BG, 3),
        (SIGNAL_COLOR, CHROME_ACTIVE, 3),
    )
    for foreground, background, minimum in pairs:
        colors = [resolve_ui_color(color, dark=dark) for color in (foreground, background)]
        levels = sorted(_luminance(color) for color in colors)
        contrast = (levels[1] + 0.05) / (levels[0] + 0.05)
        assert contrast >= minimum, (colors, round(contrast, 2), minimum)
