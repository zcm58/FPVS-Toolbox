"""Exercise the normal startup disclosure without loading the desktop."""

import os
import subprocess
import sys
from textwrap import dedent

from tests import repo_root


def test_reporting_disclosure_starts_with_saved_appearance(tmp_path):
    path = tmp_path / "settings" / "settings.ini"
    path.parent.mkdir()
    path.write_text("[appearance]\nmode = Dark\n", encoding="utf-8")
    # Startup configures process-wide settings. Keep the launcher and its UI
    # substitutes in a fresh interpreter, independent of the test import order.
    script = dedent("""
        import sys
        from unittest.mock import ANY, Mock

        reporter = Mock()
        theme = Mock()
        disclosure = Mock()

        def check_disclosure(active_reporter):
            assert active_reporter is reporter
            theme.set_appearance_mode.assert_called_once_with(ANY, "Dark")

        disclosure.disclose_automatic_reporting.side_effect = check_disclosure
        sys.modules.update({
            "PySide6": Mock(), "PySide6.QtCore": Mock(), "PySide6.QtWidgets": Mock(),
            "Main_App.gui.theme": theme, "Main_App.gui.diagnostics_preferences": disclosure,
            "Main_App.gui.icons": Mock(), "Main_App.gui.main_window": Mock(),
        })
        sys.path.insert(0, "src")
        import main
        main.start_reporting = Mock(return_value=reporter)
        main.configure_logging = Mock()
        main.run_app()
        disclosure.disclose_automatic_reporting.assert_called_once_with(reporter)
    """)
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=repo_root(), capture_output=True, text=True,
        env={**os.environ, "FPVS_CONFIG_HOME": str(tmp_path), "FPVS_DEBUG": "0"}, timeout=30,
    )
    assert result.returncode == 0, result.stderr
