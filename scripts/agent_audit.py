from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "docs" / "architecture" / "protected-paths.txt"
ACTIVE_SOURCE_LOCALIZATION = "src/Tools/SourceLocalization"
AGENT_INDEX = REPO_ROOT / "docs" / "agent-index.md"
SKILL_SCRIPT_PATHS = (
    ".agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py",
    ".agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py",
    ".agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py",
)

QACTION_BAD_IMPORT_RE = re.compile(r"^\s*from\s+PySide6\.(?:QtWidgets|QtCore)\s+import\s+.*\bQAction\b")
CUSTOMTK_IMPORT_RE = re.compile(
    r"^\s*(?:import\s+(?:customtkinter|CTkMessagebox)\b|from\s+(?:customtkinter|CTkMessagebox)\s+import\b)"
)
PRINT_RE = re.compile(r"^\s*print\s*\(")
WINDOWS_USER_PATH_RE = r"[A-Za-z]:\\" + r"Users\\" + r"[^\\\s]+"
POSIX_USER_PATH_RE = "/" + "Users/" + r"[^/\s]+"
LOCAL_PATH_RE = re.compile(f"(?:{WINDOWS_USER_PATH_RE}|{POSIX_USER_PATH_RE})")
ACTIVE_SOURCE_LOCALIZATION_REF_RE = re.compile(
    r"(?:Tools\.SourceLocalization|src[/\\]Tools[/\\]SourceLocalization)"
)

CURRENT_CODE_EXCLUDES = (
    "src/Main_App/Legacy_App/",
    "src/Tools/Average_Preprocessing/Legacy/",
    "src/Tools/Stats/Legacy/",
    "src/quarantine/",
    "src/Standalone_Scripts/",
    "src/debug/",
)

PRODUCTION_EXCLUDES = CURRENT_CODE_EXCLUDES + (
    "scripts/",
    "tests/",
)

STATS_PYSIDE6_ROOT = "src/Tools/Stats/PySide6"
STATS_PYSIDE6_ROOT_ALLOWED = {
    "__init__.py",
    "stats_core.py",
    "stats_main_window.py",
    "stats_ui_pyside6.py",
    "stats_workers.py",
}
STATS_PYSIDE6_REMOVED_ROOT_MODULES = (
    "baseline_vs_zero",
    "dv_policies",
    "dv_variants",
    "group_harmonics",
    "lmm_reporting",
    "reporting_summary",
    "shared_harmonics",
    "stats_controller",
    "stats_data_loader",
    "stats_export_formatting",
    "stats_group_contrasts",
    "stats_manual_exclusion_dialog",
    "stats_missingness",
    "stats_multigroup_ids",
    "stats_multigroup_scan",
    "stats_outlier_exclusion",
    "stats_qc_exclusion",
    "stats_qc_reports",
    "stats_run_report",
    "stats_subjects",
    "stats_window_support",
    "summary_utils",
)
STATS_PYSIDE6_PACKAGE_IMPORT_RE = re.compile(
    r"^\s*from\s+Tools\.Stats\.PySide6\s+import\s+(?P<imports>.+)$"
)


@dataclass(frozen=True)
class Issue:
    check: str
    path: str
    line: int | None
    message: str

    def format(self) -> str:
        location = self.path if self.line is None else f"{self.path}:{self.line}"
        return f"[{self.check}] {location} - {self.message}"


def _git_lines(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _normalize(path: str | Path) -> str:
    return str(path).replace("\\", "/")


def _repo_path(path: Path) -> str:
    return _normalize(path.relative_to(REPO_ROOT))


def _tracked_files() -> list[str]:
    return _git_lines("ls-files")


def _untracked_files() -> list[str]:
    return _git_lines("ls-files", "--others", "--exclude-standard")


def _tracked_and_untracked_files() -> list[str]:
    return sorted(set(_tracked_files()) | set(_untracked_files()))


def _changed_files() -> list[str]:
    return sorted(set(_git_lines("diff", "--name-only", "HEAD", "--")) | set(_untracked_files()))


def _read_text(path: str) -> list[str]:
    absolute = REPO_ROOT / path
    try:
        return absolute.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return absolute.read_text(encoding="utf-8", errors="replace").splitlines()


def _load_manifest() -> dict[str, list[str]]:
    if not MANIFEST_PATH.exists():
        raise RuntimeError(f"missing path manifest: {_repo_path(MANIFEST_PATH)}")

    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in MANIFEST_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip()
            sections.setdefault(current, [])
            continue
        if current is None:
            raise RuntimeError(f"manifest entry outside a section: {raw_line!r}")
        sections[current].append(line)
    return sections


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _is_python(path: str) -> bool:
    return path.endswith(".py")


def _is_current_code(path: str) -> bool:
    return path.startswith("src/") and _is_python(path) and not path.startswith(CURRENT_CODE_EXCLUDES)


def _is_production_code(path: str) -> bool:
    return path.startswith("src/") and _is_python(path) and not path.startswith(PRODUCTION_EXCLUDES)


def _added_lines(path: str) -> list[tuple[int, str]]:
    absolute = REPO_ROOT / path
    if path in _untracked_files():
        return list(enumerate(_read_text(path), start=1)) if absolute.exists() else []

    result = subprocess.run(
        ["git", "diff", "--unified=0", "HEAD", "--", path],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git diff failed for {path}: {result.stderr.strip()}")

    added: list[tuple[int, str]] = []
    current_line: int | None = None
    for diff_line in result.stdout.splitlines():
        if diff_line.startswith("@@"):
            match = re.search(r"\+(\d+)(?:,\d+)?", diff_line)
            current_line = int(match.group(1)) if match else None
            continue
        if current_line is None:
            continue
        if diff_line.startswith("+++") or diff_line.startswith("---"):
            continue
        if diff_line.startswith("+"):
            added.append((current_line, diff_line[1:]))
            current_line += 1
        elif diff_line.startswith("-"):
            continue
        else:
            current_line += 1
    return added


def check_protected_edits() -> list[Issue]:
    protected = _load_manifest().get("protected", [])
    issues: list[Issue] = []
    for path in _changed_files():
        normalized = _normalize(path)
        if normalized.endswith("/AGENTS.md"):
            continue
        if _matches_any(normalized, protected):
            issues.append(
                Issue(
                    "protected",
                    normalized,
                    None,
                    "protected path changed; keep legacy edits out unless explicitly approved",
                )
            )
    return issues


def check_agent_harness() -> list[Issue]:
    issues: list[Issue] = []
    if not AGENT_INDEX.exists():
        issues.append(
            Issue(
                "agent-harness",
                _repo_path(AGENT_INDEX),
                None,
                "missing compact agent command index",
            )
        )
    else:
        text = AGENT_INDEX.read_text(encoding="utf-8", errors="replace")
        for script_path in SKILL_SCRIPT_PATHS:
            if script_path not in text:
                issues.append(
                    Issue(
                        "agent-harness",
                        _repo_path(AGENT_INDEX),
                        None,
                        f"agent index does not mention {script_path}",
                    )
                )

    for script_path in SKILL_SCRIPT_PATHS:
        if not (REPO_ROOT / script_path).exists():
            issues.append(
                Issue(
                    "agent-harness",
                    script_path,
                    None,
                    "missing skill-local audit wrapper",
                )
            )
    return issues


def check_source_localization_quarantine() -> list[Issue]:
    issues: list[Issue] = []
    active_prefix = f"{ACTIVE_SOURCE_LOCALIZATION}/"

    for path in _tracked_and_untracked_files():
        normalized = _normalize(path)
        if normalized.startswith(active_prefix):
            issues.append(
                Issue(
                    "source-localization",
                    normalized,
                    None,
                    "active SourceLocalization files are not allowed; keep this code quarantined",
                )
            )

    active_path = REPO_ROOT / ACTIVE_SOURCE_LOCALIZATION
    if not active_path.exists():
        return issues

    for file_path in active_path.rglob("*"):
        if not file_path.is_file():
            continue
        parts = set(file_path.parts)
        if "__pycache__" in parts or file_path.suffix in {".pyc", ".pyo"}:
            continue
        issues.append(
            Issue(
                "source-localization",
                _repo_path(file_path),
                None,
                "non-cache file found in active SourceLocalization; quarantine or remove it",
            )
        )
    return issues


def check_gui_imports() -> list[Issue]:
    issues: list[Issue] = []
    for path in _tracked_and_untracked_files():
        normalized = _normalize(path)
        if not _is_python(normalized):
            continue
        absolute = REPO_ROOT / normalized
        if not absolute.exists():
            continue
        for line_no, line in enumerate(_read_text(normalized), start=1):
            if QACTION_BAD_IMPORT_RE.search(line):
                issues.append(
                    Issue(
                        "gui",
                        normalized,
                        line_no,
                        "import QAction from PySide6.QtGui, not QtWidgets or QtCore",
                    )
                )
            if _is_current_code(normalized) and CUSTOMTK_IMPORT_RE.search(line):
                issues.append(
                    Issue(
                        "gui",
                        normalized,
                        line_no,
                        "current runtime code must not import CustomTkinter or CTkMessagebox",
                    )
                )
    return issues


def check_added_paths() -> list[Issue]:
    issues: list[Issue] = []
    text_extensions = {".py", ".md", ".toml", ".yml", ".yaml", ".txt"}
    for path in _changed_files():
        normalized = _normalize(path)
        if Path(normalized).suffix not in text_extensions:
            continue
        for line_no, line in _added_lines(normalized):
            if LOCAL_PATH_RE.search(line):
                issues.append(
                    Issue(
                        "paths",
                        normalized,
                        line_no,
                        "new local user path detected; use project-root-relative paths or examples without machine paths",
                    )
                )
    return issues


def check_added_source_localization_refs() -> list[Issue]:
    issues: list[Issue] = []
    for path in _changed_files():
        normalized = _normalize(path)
        if normalized == "scripts/agent_audit.py":
            continue
        if not _is_python(normalized):
            continue
        for line_no, line in _added_lines(normalized):
            if ACTIVE_SOURCE_LOCALIZATION_REF_RE.search(line):
                issues.append(
                    Issue(
                        "source-localization",
                        normalized,
                        line_no,
                        "new active SourceLocalization reference detected; keep Source Localization quarantined",
                    )
                )
    return issues


def check_added_prints() -> list[Issue]:
    issues: list[Issue] = []
    for path in _changed_files():
        normalized = _normalize(path)
        if not _is_production_code(normalized):
            continue
        for line_no, line in _added_lines(normalized):
            if PRINT_RE.search(line):
                issues.append(
                    Issue(
                        "prints",
                        normalized,
                        line_no,
                        "new production print call detected; use structured logging",
                    )
                )
    return issues


def check_stats_pyside6_structure() -> list[Issue]:
    issues: list[Issue] = []
    removed_root_paths = {
        f"Tools.Stats.PySide6.{module}": module
        for module in STATS_PYSIDE6_REMOVED_ROOT_MODULES
    }

    for path in _tracked_and_untracked_files():
        normalized = _normalize(path)
        absolute = REPO_ROOT / normalized
        if not absolute.exists():
            continue

        if (
            normalized.startswith(f"{STATS_PYSIDE6_ROOT}/")
            and _is_python(normalized)
            and "/" not in normalized.removeprefix(f"{STATS_PYSIDE6_ROOT}/")
        ):
            filename = Path(normalized).name
            if filename not in STATS_PYSIDE6_ROOT_ALLOWED:
                issues.append(
                    Issue(
                        "stats-pyside6",
                        normalized,
                        None,
                        "unexpected root Stats PySide6 module; place implementation in a functional subpackage or update the allowlist with rationale",
                    )
                )

        if not _is_python(normalized):
            continue
        if normalized == "scripts/agent_audit.py":
            continue

        for line_no, line in enumerate(_read_text(normalized), start=1):
            for import_path, module in removed_root_paths.items():
                if import_path in line:
                    issues.append(
                        Issue(
                            "stats-pyside6",
                            normalized,
                            line_no,
                            f"old root Stats PySide6 import {import_path}; import the functional subpackage module instead",
                        )
                    )

            package_import = STATS_PYSIDE6_PACKAGE_IMPORT_RE.match(line)
            if not package_import:
                continue
            imported_names = {
                item.strip().split(" as ", 1)[0].strip()
                for item in package_import.group("imports").split(",")
            }
            for module in STATS_PYSIDE6_REMOVED_ROOT_MODULES:
                if module in imported_names:
                    issues.append(
                        Issue(
                            "stats-pyside6",
                            normalized,
                            line_no,
                            f"old root Stats PySide6 package import {module}; import Tools.Stats.PySide6.analysis/data/qc/reporting/ui module instead",
                        )
                    )
    return issues


CHECKS = {
    "agent-harness": check_agent_harness,
    "protected": check_protected_edits,
    "source-localization": check_source_localization_quarantine,
    "source-localization-refs": check_added_source_localization_refs,
    "gui": check_gui_imports,
    "paths": check_added_paths,
    "prints": check_added_prints,
    "stats-pyside6": check_stats_pyside6_structure,
}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run fast repo invariants for agent work.")
    parser.add_argument(
        "--check",
        choices=["all", *CHECKS.keys()],
        default="all",
        help="Run one check group instead of the full audit.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    selected = CHECKS if args.check == "all" else {args.check: CHECKS[args.check]}

    issues: list[Issue] = []
    try:
        for check in selected.values():
            issues.extend(check())
    except RuntimeError as exc:
        print(f"agent audit error: {exc}", file=sys.stderr)
        return 2

    if issues:
        print(f"Agent audit failed: {len(issues)} issue(s)")
        for issue in issues:
            print(issue.format())
        return 1

    names = ", ".join(selected)
    print(f"Agent audit passed: {names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
