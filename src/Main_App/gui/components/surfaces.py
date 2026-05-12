"""Shared app-window and dialog surface primitives."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget


@dataclass(frozen=True)
class SurfaceSize:
    """Standard optional sizing contract for GUI surfaces."""

    width: int
    height: int
    min_width: int | None = None
    min_height: int | None = None


def configure_window_surface(
    window: QWidget,
    *,
    title: str | None = None,
    size: SurfaceSize | None = None,
    fpvs_surface: bool = True,
) -> QWidget:
    """Apply shared shell metadata and optional geometry to a top-level surface."""
    if title is not None:
        window.setWindowTitle(title)
    if fpvs_surface:
        window.setProperty("fpvsSurface", True)
    if size is not None:
        window.resize(size.width, size.height)
        if size.min_width is not None and size.min_height is not None:
            window.setMinimumSize(size.min_width, size.min_height)
        elif size.min_width is not None:
            window.setMinimumWidth(size.min_width)
        elif size.min_height is not None:
            window.setMinimumHeight(size.min_height)
    return window


class AppDialog(QDialog):
    """Base dialog shell for new FPVS modal surfaces."""

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        *,
        size: SurfaceSize | None = None,
    ) -> None:
        super().__init__(parent)
        configure_window_surface(self, title=title, size=size)
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(16, 16, 16, 16)
        self.root_layout.setSpacing(12)
