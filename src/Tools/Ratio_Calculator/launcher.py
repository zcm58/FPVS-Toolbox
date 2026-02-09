from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def open_ratio_calculator_tool(parent: Any | None = None) -> None:
    cmd = [sys.executable]
    if getattr(sys, "frozen", False):
        cmd.append("--run-ratio-calculator")
    else:
        script = Path(__file__).resolve().parent / "ratio_calculator.py"
        cmd.append(str(script))
    env = os.environ.copy()
    proj = getattr(parent, "currentProject", None)
    if proj and hasattr(proj, "project_root"):
        env["FPVS_PROJECT_ROOT"] = str(proj.project_root)
    subprocess.Popen(cmd, close_fds=True, env=env)
