"""Check native graphics capability before entering VTK's rendering backend."""

from __future__ import annotations

from typing import Any


_REQUIREMENT = (
    "LORETA 3D rendering requires desktop OpenGL 3.2 or later. "
    "Update your graphics driver or use a supported graphics session."
)


def _verify_context(context: Any) -> None:
    # Qt may return a lower version than requested, so successful creation alone
    # does not establish VTK's minimum desktop OpenGL requirement.
    if not context.create() or not context.isValid():
        raise RuntimeError(_REQUIREMENT)
    if context.isOpenGLES() or context.format().version() < (3, 2):
        raise RuntimeError(_REQUIREMENT)


def require_desktop_opengl(parent: Any) -> None:
    """Fail recoverably when the current display cannot create the required GL context."""
    from PySide6.QtGui import QOpenGLContext, QSurfaceFormat

    requested = QSurfaceFormat()
    requested.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    requested.setVersion(3, 2)
    requested.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    context = QOpenGLContext(parent)
    context.setScreen(parent.screen())
    context.setFormat(requested)
    try:
        _verify_context(context)
    finally:
        context.deleteLater()
