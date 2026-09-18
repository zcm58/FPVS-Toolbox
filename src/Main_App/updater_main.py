"""Independent updater entry point; worker and packaging modes never import Qt."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from Main_App.updates.application import APP_VERSION as __version__
from Main_App.updates.helper_protocol import PROTOCOL_VERSION


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FPVS Toolbox Update & Repair")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--stdio", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--packaging-check", type=Path, metavar="REPORT_JSON")
    mode.add_argument("--gui-smoke", type=Path, metavar="REPORT_JSON")
    args = parser.parse_args(argv)
    if args.packaging_check is not None:
        args.packaging_check.write_text(
            json.dumps(
                {
                    "version": __version__,
                    "frozen": bool(getattr(sys, "frozen", False)),
                    "protocol_version": PROTOCOL_VERSION,
                    "gui_loaded": any(
                        name.startswith("PySide6") or name.startswith("Main_App.gui.") for name in sys.modules
                    ),
                    "analysis_loaded": any(
                        name == "config"
                        or name.split(".")[0] in {"numpy", "scipy", "pandas", "mne", "Tools"}
                        or name.startswith("Main_App.projects")
                        for name in sys.modules
                    ),
                }
            ),
            encoding="utf-8",
        )
        return 0

    from Main_App.updates.helper_service import serve_stdio

    if args.stdio:
        return serve_stdio()

    from Main_App.updates.helper_runtime import (
        helper_command,
        is_staged_helper,
        spawn_helper_command,
    )

    # The Start Menu launches the installed copy. Move execution outside the app
    # directory before showing a window so setup can replace this helper as well.
    startup_error: Exception | None = None
    try:
        if getattr(sys, "frozen", False) and not args.gui_smoke and not is_staged_helper():
            if args.apply:
                raise RuntimeError("An install handoff must use the staged updater.")
            spawn_helper_command(helper_command())
            return 0
    except Exception as error:
        logging.getLogger(__name__).exception("updater_start_failed")
        startup_error = error

    from Main_App.gui.updater_window import run_updater_gui

    return run_updater_gui(apply_mode=args.apply, smoke_report=args.gui_smoke, startup_error=startup_error)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
