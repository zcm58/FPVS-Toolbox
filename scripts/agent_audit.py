from __future__ import annotations

import argparse
import ast
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
ARCHITECTURE_MAP = REPO_ROOT / "ARCHITECTURE.md"
EXEC_PLANS_README = REPO_ROOT / "docs" / "exec-plans" / "README.md"
TECH_DEBT_TRACKER = REPO_ROOT / "docs" / "exec-plans" / "tech-debt-tracker.md"
MAIN_APP_REFACTOR_PLAN = REPO_ROOT / "docs" / "exec-plans" / "active" / "main-app-refactor.md"
SKILL_SCRIPT_PATHS = (
    ".agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py",
    ".agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py",
    ".agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py",
)
KNOWLEDGE_BASE_PATHS = (
    "docs/README.md",
    "docs/design-docs/index.md",
    "docs/design-docs/core-beliefs.md",
    "docs/product-specs/index.md",
    "docs/references/index.md",
    "docs/generated/README.md",
    "docs/DESIGN.md",
    "docs/FRONTEND.md",
    "docs/PLANS.md",
    "docs/PRODUCT_SENSE.md",
    "docs/QUALITY_SCORE.md",
    "docs/RELIABILITY.md",
    "docs/SECURITY.md",
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
    "src/Tools/Average_Preprocessing/Legacy/",
    "src/quarantine/",
    "src/Standalone_Scripts/",
)
RETIRED_PATH_PREFIXES = (
    "src/Main_App/Legacy_App/",
)

PRODUCTION_EXCLUDES = CURRENT_CODE_EXCLUDES + (
    "scripts/",
    "tests/",
    "src/Tools/Stats/cli/",
)

STATS_REMOVED_NAMESPACE_PREFIXES = (
    "src/Tools/Stats/Legacy/",
    "src/Tools/Stats/PySide6/",
)
STATS_ROOT = "src/Tools/Stats"
STATS_ROOT_ALLOWED_PYTHON = {"__init__.py"}
STATS_COMPAT_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+Tools\.Stats\.(?:Legacy|PySide6)(?:\.|\b)"
)
STATS_REMOVED_NAMESPACE_PATH_RE = re.compile(
    r"(?:"
    r"src[/\\]Tools[/\\]Stats[/\\](?:Legacy|PySide6)"
    r"|Stats[/\\](?:Legacy|PySide6)"
    r"|[\"']Stats[\"']\s*/\s*[\"'](?:Legacy|PySide6)[\"']"
    r")"
)
TKINTER_IMPORT_RE = re.compile(r"^\s*(?:import\s+tkinter\b|from\s+tkinter\s+import\b)")
STALE_STATS_NAMING_RE = re.compile(
    r"(?:Stats PySide6 (?:workflow|tool|window|statistics workflow)|Legacy Stats workflow)"
)
STATS_REPORTING_ROOT = "src/Tools/Stats/reporting"
STATS_REPORTING_MAX_MODULE_LINES = 600
STATS_REPORTING_MAX_SYMBOL_LINES = 160
GARBAGE_PATH_PATTERNS = (
    "*/__pycache__/*",
    "*.pyc",
    "*.pyo",
    ".pytest_cache/*",
    ".mypy_cache/*",
    ".ruff_cache/*",
    ".codex-tmp/*",
    ".codex-pytest-tmp/*",
    ".tmp/*",
    "codex_pytest_tmp/*",
    "test_tmp/*",
)
GARBAGE_MARKER_RE = re.compile(
    r"\b(?:TODO|FIXME|HACK|YOLO)\b|quick[- ]?fix|temporary workaround",
    re.IGNORECASE,
)
BROAD_EXCEPTION_RE = re.compile(r"^\s*except\s+Exception\s*:\s*(?:pass\s*)?$")
BROAD_EXCEPTION_BASELINES = {
    # Moved unchanged during PySide6_App folder retirement. Keep detecting any
    # increase while avoiding a false positive for pre-existing boundary debt.
    "src/Main_App/processing/processing_controller.py": (
        "src/Main_App/PySide6_App/Backend/processing_controller.py"
    ),
    "src/Main_App/diagnostics/audit.py": (
        "src/Main_App/PySide6_App/utils/audit.py"
    ),
    "src/Main_App/diagnostics/event_time_lock_report.py": (
        "src/Main_App/PySide6_App/diagnostics/event_time_lock_report.py"
    ),
}


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


def _file_text_at_head(path: str) -> str:
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD:{path}"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout


def _broad_exception_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if BROAD_EXCEPTION_RE.search(line))


def _broad_exception_increase_allowed(path: str) -> bool:
    baseline_path = BROAD_EXCEPTION_BASELINES.get(path)
    if not baseline_path:
        return False
    current_path = REPO_ROOT / path
    if not current_path.exists():
        return False
    current_count = _broad_exception_count(
        current_path.read_text(encoding="utf-8", errors="replace")
    )
    baseline_count = _broad_exception_count(_file_text_at_head(baseline_path))
    return baseline_count > 0 and current_count <= baseline_count


def check_protected_edits() -> list[Issue]:
    protected = _load_manifest().get("protected", [])
    issues: list[Issue] = []
    changed = {_normalize(path) for path in _changed_files()}
    has_migration_context = bool(
        {
            "docs/exec-plans/active/main-app-refactor.md",
            "docs/architecture/legacy-boundaries.md",
            "AGENTS.md",
        }
        & changed
    )
    for path in _changed_files():
        normalized = _normalize(path)
        if normalized.endswith("/AGENTS.md"):
            continue
        if _matches_any(normalized, protected) and not has_migration_context:
            issues.append(
                Issue(
                    "protected",
                    normalized,
                    None,
                    "retired/protected legacy path changed without plan/doc context; boundary cleanup must preserve the processing pipeline",
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
        if "docs/exec-plans/active/main-app-refactor.md" not in text:
            issues.append(
                Issue(
                    "agent-harness",
                    _repo_path(AGENT_INDEX),
                    None,
                    "agent index does not mention the active Main_App refactor plan",
                )
            )

    if not ARCHITECTURE_MAP.exists():
        issues.append(
            Issue(
                "agent-harness",
                _repo_path(ARCHITECTURE_MAP),
                None,
                "missing top-level architecture map",
            )
        )
    else:
        text = ARCHITECTURE_MAP.read_text(encoding="utf-8", errors="replace")
        if "docs/exec-plans" not in text:
            issues.append(
                Issue(
                    "agent-harness",
                    _repo_path(ARCHITECTURE_MAP),
                    None,
                    "architecture map does not mention execution plans",
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
    for plan_path, message in (
        (EXEC_PLANS_README, "missing execution-plan directory README"),
        (TECH_DEBT_TRACKER, "missing technical debt tracker"),
        (MAIN_APP_REFACTOR_PLAN, "missing active Main_App refactor plan"),
    ):
        if not plan_path.exists():
            issues.append(
                Issue(
                    "agent-harness",
                    _repo_path(plan_path),
                    None,
                    message,
                )
            )
    for required_path in KNOWLEDGE_BASE_PATHS:
        if not (REPO_ROOT / required_path).exists():
            issues.append(
                Issue(
                    "agent-harness",
                    required_path,
                    None,
                    "missing structured docs knowledge-base path",
                )
            )
    for path in _tracked_and_untracked_files():
        normalized = _normalize(path)
        absolute = REPO_ROOT / normalized
        if absolute.exists() and normalized.startswith(RETIRED_PATH_PREFIXES):
            issues.append(
                Issue(
                    "agent-harness",
                    normalized,
                    None,
                    "retired Legacy_App path exists; use purpose-based Main_App packages instead",
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
                    "active SourceLocalization files are not allowed; the feature is removed from active runtime",
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
                "non-cache file found in active SourceLocalization; remove it unless restoring the feature explicitly",
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
            if normalized != "scripts/agent_audit.py" and (
                CUSTOMTK_IMPORT_RE.search(line) or TKINTER_IMPORT_RE.search(line)
            ):
                issues.append(
                    Issue(
                        "gui",
                        normalized,
                        line_no,
                        "repo code must not import Tkinter, CustomTkinter, or CTkMessagebox; use PySide6",
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
                        "new active SourceLocalization reference detected; the feature is removed from active runtime",
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


def check_stats_structure() -> list[Issue]:
    issues: list[Issue] = []

    for path in _tracked_and_untracked_files():
        normalized = _normalize(path)
        absolute = REPO_ROOT / normalized
        if not absolute.exists():
            continue

        if normalized.startswith(STATS_REMOVED_NAMESPACE_PREFIXES):
            issues.append(
                Issue(
                    "stats-structure",
                    normalized,
                    None,
                    "removed Stats compatibility namespace found; active code belongs in Tools.Stats functional packages",
                )
            )

        if (
            normalized.startswith(f"{STATS_ROOT}/")
            and _is_python(normalized)
            and "/" not in normalized.removeprefix(f"{STATS_ROOT}/")
            and Path(normalized).name not in STATS_ROOT_ALLOWED_PYTHON
        ):
            issues.append(
                Issue(
                    "stats-structure",
                    normalized,
                    None,
                    "Stats root should contain package/docs files only; move implementation into a functional subpackage",
                )
            )

        if not _is_python(normalized):
            continue
        if normalized == "scripts/agent_audit.py":
            continue

        for line_no, line in enumerate(_read_text(normalized), start=1):
            if (
                normalized.startswith("src/Tools/Stats/")
                and TKINTER_IMPORT_RE.search(line)
            ):
                issues.append(
                    Issue(
                        "stats-structure",
                        normalized,
                        line_no,
                        "active Stats code must not import tkinter; keep GUI code PySide6-only",
                    )
                )

            if STATS_COMPAT_IMPORT_RE.search(line):
                issues.append(
                    Issue(
                        "stats-structure",
                        normalized,
                        line_no,
                        "removed Stats compatibility import; use canonical Tools.Stats.<area> modules",
                    )
                )

            if STATS_REMOVED_NAMESPACE_PATH_RE.search(line):
                issues.append(
                    Issue(
                        "stats-structure",
                        normalized,
                        line_no,
                        "removed Stats compatibility path reference; use canonical src/Tools/Stats/<area> paths",
                    )
                )

            if normalized.startswith("src/Tools/Stats/") and STALE_STATS_NAMING_RE.search(line):
                issues.append(
                    Issue(
                        "stats-structure",
                        normalized,
                        line_no,
                        "stale Stats PySide6/Legacy workflow wording; use neutral Stats package naming",
                    )
                )
    return issues


def check_stats_reporting_legibility() -> list[Issue]:
    issues: list[Issue] = []

    for path in _tracked_and_untracked_files():
        normalized = _normalize(path)
        if not (
            normalized.startswith(f"{STATS_REPORTING_ROOT}/")
            and _is_python(normalized)
            and Path(normalized).name != "__init__.py"
        ):
            continue
        absolute = REPO_ROOT / normalized
        if not absolute.exists():
            continue

        lines = _read_text(normalized)
        if len(lines) > STATS_REPORTING_MAX_MODULE_LINES:
            issues.append(
                Issue(
                    "stats-reporting-legibility",
                    normalized,
                    None,
                    "Stats reporting module is oversized; split summary/reporting logic into focused modules by responsibility",
                )
            )

        try:
            tree = ast.parse("\n".join(lines), filename=normalized)
        except SyntaxError as exc:
            issues.append(
                Issue(
                    "stats-reporting-legibility",
                    normalized,
                    exc.lineno,
                    f"could not parse reporting module while checking legibility: {exc.msg}",
                )
            )
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            end_lineno = getattr(node, "end_lineno", node.lineno) or node.lineno
            span = end_lineno - node.lineno + 1
            if span <= STATS_REPORTING_MAX_SYMBOL_LINES:
                continue
            issues.append(
                Issue(
                    "stats-reporting-legibility",
                    normalized,
                    node.lineno,
                    f"oversized {type(node).__name__} {node.name!r} spans {span} lines; split reporting summary logic by responsibility",
                )
            )
    return issues


def check_garbage_collection() -> list[Issue]:
    issues: list[Issue] = []

    for path in _tracked_and_untracked_files():
        normalized = _normalize(path)
        if _matches_any(normalized, list(GARBAGE_PATH_PATTERNS)):
            issues.append(
                Issue(
                    "garbage-collection",
                    normalized,
                    None,
                    "cache, build, or temporary artifact is visible to git; keep generated garbage ignored or remove it",
                )
            )

    for path in _changed_files():
        normalized = _normalize(path)
        if normalized == "scripts/agent_audit.py":
            continue
        if not (_is_python(normalized) or Path(normalized).suffix in {".md", ".txt"}):
            continue
        for line_no, line in _added_lines(normalized):
            if GARBAGE_MARKER_RE.search(line):
                issues.append(
                    Issue(
                        "garbage-collection",
                        normalized,
                        line_no,
                        "new TODO/FIXME/HACK-style marker; move debt to docs/exec-plans/tech-debt-tracker.md or an active plan",
                    )
                )
            if (
                _is_production_code(normalized)
                and BROAD_EXCEPTION_RE.search(line)
                and not _broad_exception_increase_allowed(normalized)
            ):
                issues.append(
                    Issue(
                        "garbage-collection",
                        normalized,
                        line_no,
                        "new broad exception handler; handle a specific exception or document why the boundary is intentionally broad",
                    )
                )
    return issues


CHECKS = {
    "agent-harness": check_agent_harness,
    "garbage-collection": check_garbage_collection,
    "protected": check_protected_edits,
    "source-localization": check_source_localization_quarantine,
    "source-localization-refs": check_added_source_localization_refs,
    "gui": check_gui_imports,
    "paths": check_added_paths,
    "prints": check_added_prints,
    "stats-reporting-legibility": check_stats_reporting_legibility,
    "stats-structure": check_stats_structure,
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
