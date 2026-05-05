from __future__ import annotations

# ruff: noqa: E402

import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["FPVS_TEST_MODE"] = "1"

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QWidget


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def find_widget_by_role(parent: QWidget, role: str) -> QWidget | None:
    for widget in parent.findChildren(QWidget):
        if widget.property("role") == role:
            return widget
    return None


def install_stub_module(name: str, **attrs: object) -> None:
    module = ModuleType(name)
    for attr_name, attr_value in attrs.items():
        setattr(module, attr_name, attr_value)
    sys.modules[name] = module


def install_gui_only_stubs() -> None:
    class NumpyStub(ModuleType):
        ndarray = list

        def array(self, values: object, dtype: object | None = None) -> list[object]:
            return list(values) if isinstance(values, (list, tuple)) else [values]

    class PsutilStub(ModuleType):
        @staticmethod
        def virtual_memory() -> object:
            return type("VirtualMemory", (), {"total": 8 * 1024 * 1024 * 1024})()

    class DummyToolWindow(QWidget):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)

    class ProcessingMixin:
        pass

    class PostProcessWorker:
        pass

    sys.modules.setdefault("numpy", NumpyStub("numpy"))
    sys.modules.setdefault("psutil", PsutilStub("psutil"))
    install_stub_module(
        "Main_App.Shared.post_process",
        post_process=lambda *args, **kwargs: None,
    )
    install_stub_module(
        "Main_App.Shared.processing_mixin",
        ProcessingMixin=ProcessingMixin,
    )
    install_stub_module(
        "Main_App.Legacy_App.debug_utils",
        messagebox=SimpleNamespace(),
    )
    install_stub_module(
        "Main_App.PySide6_App.Backend.processing_controller",
        _animate_progress_to=lambda *args, **kwargs: None,
        prepare_batch_files=lambda project: [],
    )
    install_stub_module(
        "Main_App.PySide6_App.GUI.update_manager",
        cleanup_old_executable=lambda: None,
        check_for_updates_on_launch=lambda *args, **kwargs: None,
        check_for_updates_async=lambda *args, **kwargs: None,
    )
    install_stub_module(
        "Main_App.PySide6_App.workers.processing_worker",
        PostProcessWorker=PostProcessWorker,
    )
    install_stub_module(
        "Main_App.workers.processing_worker",
        PostProcessWorker=PostProcessWorker,
    )
    install_stub_module(
        "Tools.Average_Preprocessing.New_PySide6.main_window",
        AdvancedAveragingWindow=DummyToolWindow,
    )
    install_stub_module(
        "Tools.Stats",
        StatsWindow=DummyToolWindow,
    )
    install_stub_module(
        "Tools.Ratio_Calculator.launcher",
        open_ratio_calculator_tool=lambda *args, **kwargs: None,
    )
    install_stub_module(
        "Tools.Individual_Detectability.launcher",
        open_individual_detectability_tool=lambda *args, **kwargs: None,
    )


def main() -> int:
    smoke_root = REPO_ROOT / ".tmp"
    smoke_root.mkdir(parents=True, exist_ok=True)
    config_root = Path(tempfile.mkdtemp(prefix="fpvs-wave3-smoke-", dir=smoke_root))
    try:
        os.environ["XDG_CONFIG_HOME"] = str(config_root)
        install_gui_only_stubs()

        from Main_App.PySide6_App.GUI import main_window as main_window_module

        projects_root = config_root
        main_window_module.select_projects_root = (
            lambda self: setattr(self, "projectsRoot", projects_root)
        )

        app = QApplication.instance() or QApplication([])
        window = main_window_module.MainWindow()
        window.show()
        app.processEvents()
        wait(240)
        app.processEvents()

        assert getattr(window, "_launch_reveal_done", False)
        assert window.findChild(QWidget, "landing_welcome_card") is not None
        assert window.landing_card.graphicsEffect() is None
        assert window.btn_create_project.text() == "Create New Project"
        assert window.btn_open_project.text() == "Open Existing Project"
        assert (
            window.landing_version_label.text()
            == f"FPVS Toolbox v{main_window_module.FPVS_TOOLBOX_VERSION}"
        )

        assert find_widget_by_role(window.sidebar, "btn_home") is not None
        assert window.findChild(QWidget, "sidebar_tools_group") is not None
        assert window.findChild(QWidget, "sidebar_utilities_group") is not None

        window.stacked.setCurrentIndex(1)
        app.processEvents()
        wait(60)
        app.processEvents()

        assert window.findChild(QWidget, "preprocessing_info_strip") is not None
        assert window.findChild(QWidget, "preprocessing_info_icon") is not None
        assert window.findChild(QWidget, "input_folder_row") is not None
        active_row = (
            window.row_single_file if window.rb_single.isChecked() else window.row_input_folder
        )
        assert active_row.isVisible()

        window.hide()
        app.processEvents()
        window.show()
        wait(60)
        app.processEvents()
        assert window.landing_card.graphicsEffect() is None
        assert getattr(window, "_launch_reveal_animation", None) is None

        window.close()
        app.processEvents()
    finally:
        shutil.rmtree(config_root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
