"""Compatibility wrapper for :mod:`Main_App.gui.theme`."""

from Main_App.gui.theme import (  # noqa: F401
    DEFAULT_LIGHT_THEME,
    LIGHT_THEME_FUSION,
    LIGHT_THEME_MATERIAL,
    LightThemeName,
    apply_fpvs_theme,
    apply_fusion_light_palette,
    apply_light_palette,
    apply_material_light_theme,
    build_fpvs_app_stylesheet,
)

__all__ = [
    "DEFAULT_LIGHT_THEME",
    "LIGHT_THEME_FUSION",
    "LIGHT_THEME_MATERIAL",
    "LightThemeName",
    "apply_fpvs_theme",
    "apply_fusion_light_palette",
    "apply_light_palette",
    "apply_material_light_theme",
    "build_fpvs_app_stylesheet",
]
