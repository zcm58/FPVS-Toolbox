"""Configure bundled Qt paths without importing Qt in updater worker processes."""

import os
import sys


def configure_qt_paths() -> None:
    root = sys._MEIPASS
    qt_root = os.path.join(root, "PySide6")
    os.environ["QT_PLUGIN_PATH"] = os.path.join(qt_root, "plugins")
    os.environ["QML2_IMPORT_PATH"] = os.path.join(qt_root, "qml")
    os.environ["PATH"] = root + os.pathsep + os.environ.get("PATH", "")


configure_qt_paths()
del configure_qt_paths
