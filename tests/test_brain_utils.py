import os
import sys
import types
import importlib.util


def _import_brain_utils(monkeypatch):
    dummy = types.SimpleNamespace(viz=types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'mne', dummy)
    monkeypatch.setitem(sys.modules, 'mne.viz', dummy.viz)

    path = os.path.join(
        os.path.dirname(__file__), '..', 'src', 'Tools', 'SourceLocalization', 'brain_utils.py'
    )
    spec = importlib.util.spec_from_file_location('brain_utils', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DummyActor:
    def __init__(self):
        self.opacity = None

    def GetProperty(self):
        return self

    def SetOpacity(self, val):
        self.opacity = val


class DummyPlotter:
    def __init__(self):
        self.render_calls = 0

    def render(self):
        self.render_calls += 1


class DummyRenderer:
    def __init__(self):
        self.plotter = DummyPlotter()


class DummyLayeredMesh:
    """Simplified stand-in for mne.viz._LayeredMesh."""

    def __init__(self):
        self.actor = DummyActor()


def test_set_brain_alpha_applies_and_renders(monkeypatch):
    module = _import_brain_utils(monkeypatch)
    brain = types.SimpleNamespace(
        _renderer=DummyRenderer(),
        _actors={"a": DummyActor(), "b": DummyActor()},
    )

    module._set_brain_alpha(brain, 0.25)

    assert all(a.opacity == 0.25 for a in brain._actors.values())
    assert brain._renderer.plotter.render_calls == 1


def test_save_brain_screenshots(tmp_path, monkeypatch):
    module = _import_brain_utils(monkeypatch)
    views, saved = [], []
    brain = types.SimpleNamespace(
        _renderer=DummyRenderer(),
        _actors={"a": DummyActor()},
        show_view=lambda view: views.append(view),
        save_image=lambda path: saved.append(path),
    )

    module._set_brain_alpha(brain, 0.5)
    module.save_brain_screenshots(brain, str(tmp_path))

    assert views == ["lat", "rostral", "dorsal"]
    assert len(saved) == 4
    assert all(path.startswith(str(tmp_path)) for path in saved)



class DummyLayeredMesh:
    def __init__(self):
        self.actor = DummyActor()


def test_set_brain_alpha_no_values(monkeypatch):
    module = _import_brain_utils(monkeypatch)
    mesh = DummyLayeredMesh()
    brain = types.SimpleNamespace(
        _renderer=DummyRenderer(),
        _layered_meshes={"lh": mesh},

    )

    module._set_brain_alpha(brain, 0.75)


    assert mesh.actor.opacity == 0.75

    assert brain._renderer.plotter.render_calls == 1
