"""Native context decisions without creating Qt widgets or a graphics context."""

from types import SimpleNamespace

import pytest

from Tools.LORETA_Visualizer.graphics_support import _verify_context


@pytest.mark.parametrize(
    "created,valid,gles,version",
    [(False, False, False, (0, 0)), (True, False, False, (3, 2)),
     (True, True, False, (1, 1)), (True, True, False, (3, 1)),
     (True, True, True, (3, 2))],
)
def test_unsupported_native_graphics_fail_before_vtk(created, valid, gles, version):
    context = SimpleNamespace(
        create=lambda: created,
        isValid=lambda: valid,
        isOpenGLES=lambda: gles,
        format=lambda: SimpleNamespace(version=lambda: version),
    )
    with pytest.raises(RuntimeError, match="desktop OpenGL 3.2"):
        _verify_context(context)


@pytest.mark.parametrize("version", [(3, 2), (3, 3), (4, 6)])
def test_supported_desktop_context_is_accepted(version):
    context = SimpleNamespace(
        create=lambda: True,
        isValid=lambda: True,
        isOpenGLES=lambda: False,
        format=lambda: SimpleNamespace(version=lambda: version),
    )
    _verify_context(context)
