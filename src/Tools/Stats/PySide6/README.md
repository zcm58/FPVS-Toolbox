# Stats PySide6 Compatibility Namespace

Active Stats code now lives under `src/Tools/Stats/<functional area>/`.

This package remains only for temporary compatibility with old imports such as `Tools.Stats.PySide6.stats_ui_pyside6`. New code should import from `Tools.Stats.ui`, `Tools.Stats.controller`, `Tools.Stats.workers`, `Tools.Stats.analysis`, and related top-level functional packages.

See `src/Tools/Stats/README.md` for the active architecture.
