"""Compatibility wrapper for the legacy ``eloreta_runner`` module."""

import importlib.util
import os

_runner_path = os.path.join(os.path.dirname(__file__), "runner.py")
_spec = importlib.util.spec_from_file_location("runner", _runner_path)
_runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_runner)

for name, val in vars(_runner).items():
    globals()[name] = val
