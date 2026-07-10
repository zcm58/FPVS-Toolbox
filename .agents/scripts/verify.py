"""Run the smallest safe verification bundle for an FPVS Toolbox change."""

from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / ".agents" / "verification.toml"
AGENT_AUDIT = REPO_ROOT / ".agents" / "scripts" / "audit" / "agent_audit.py"
QT_OPT_IN_ENV = "FPVS_ALLOW_QT_TESTS"


@dataclass(frozen=True)
class VerificationScope:
    name: str
    audits: tuple[str, ...]
    tests: tuple[str, ...]
    include: tuple[str, ...]
    manual_smoke: tuple[str, ...]


def resolve_repo_python(repo_root: Path = REPO_ROOT) -> Path:
    """Prefer the checkout's .venv1 interpreter, then .venv, then this Python."""

    suffixes = (
        Path("Scripts/python.exe"),
        Path("bin/python"),
    )
    for environment in (".venv1", ".venv"):
        for suffix in suffixes:
            candidate = repo_root / environment / suffix
            if candidate.is_file():
                return candidate.resolve()
    return Path(sys.executable).resolve()


def load_scopes(config_path: Path = CONFIG_PATH) -> tuple[dict[str, VerificationScope], Path]:
    """Load the machine-readable verification routing map."""

    with config_path.open("rb") as handle:
        payload = tomllib.load(handle)
    if payload.get("version") != 1:
        raise ValueError(".agents/verification.toml must declare version = 1")
    raw_scopes = payload.get("scopes")
    if not isinstance(raw_scopes, Mapping) or not raw_scopes:
        raise ValueError(".agents/verification.toml has no scopes")
    scopes: dict[str, VerificationScope] = {}
    for name, raw in raw_scopes.items():
        if not isinstance(raw, Mapping):
            raise ValueError(f"verification scope {name!r} must be a table")
        scopes[str(name)] = VerificationScope(
            name=str(name),
            audits=_string_tuple(raw.get("audits"), field=f"{name}.audits"),
            tests=_string_tuple(raw.get("tests"), field=f"{name}.tests"),
            include=_string_tuple(raw.get("include"), field=f"{name}.include"),
            manual_smoke=_string_tuple(raw.get("manual_smoke"), field=f"{name}.manual_smoke"),
        )
    registry_value = payload.get("qt_registry")
    if not isinstance(registry_value, str) or not registry_value.strip():
        raise ValueError(".agents/verification.toml must declare qt_registry")
    return scopes, (REPO_ROOT / registry_value).resolve()


def _string_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"verification field {field} must be a string array")
    return tuple(value)


def read_qt_registry(path: Path) -> frozenset[str]:
    """Read normalized test paths that require an explicit Qt opt-in."""

    if not path.is_file():
        raise ValueError(f"Qt test registry does not exist: {path}")
    entries = {
        line.strip().replace("\\", "/")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    return frozenset(entries)


def validate_config(
    scopes: Mapping[str, VerificationScope],
    qt_registry_path: Path,
    *,
    repo_root: Path = REPO_ROOT,
) -> list[str]:
    """Return configuration errors without running any verification commands."""

    errors: list[str] = []
    try:
        qt_tests = read_qt_registry(qt_registry_path)
    except ValueError as exc:
        return [str(exc)]

    for entry in sorted(qt_tests):
        if not (repo_root / entry).is_file():
            errors.append(f"Qt registry path does not exist: {entry}")

    for scope in scopes.values():
        for test_path in scope.tests:
            absolute = repo_root / test_path
            if not absolute.exists():
                errors.append(f"{scope.name}: test path does not exist: {test_path}")
                continue
            candidates = (
                [absolute]
                if absolute.is_file()
                else sorted(absolute.rglob("test_*.py"))
            )
            for candidate in candidates:
                relative = candidate.relative_to(repo_root).as_posix()
                if relative in qt_tests:
                    errors.append(
                        f"{scope.name}: focused local bundle includes Qt test: {relative}"
                    )
    return errors


def changed_files(repo_root: Path = REPO_ROOT) -> tuple[str, ...]:
    """Return tracked worktree changes and untracked files."""

    tracked = _git_lines(repo_root, "diff", "--name-only", "HEAD", "--")
    untracked = _git_lines(repo_root, "ls-files", "--others", "--exclude-standard")
    return tuple(sorted(set(tracked) | set(untracked)))


def _git_lines(repo_root: Path, *args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def scope_python_files(scope: VerificationScope, paths: Iterable[str]) -> tuple[str, ...]:
    """Filter changed Python paths through a scope's include patterns."""

    selected = []
    for path in paths:
        normalized = path.replace("\\", "/")
        if not normalized.endswith(".py"):
            continue
        if any(fnmatch.fnmatch(normalized, pattern) for pattern in scope.include):
            selected.append(normalized)
    return tuple(sorted(set(selected)))


def build_commands(
    scope: VerificationScope,
    *,
    tier: str,
    python: Path,
    changed: Sequence[str],
) -> list[list[str]]:
    """Build commands for a focused, precommit, or CI verification tier."""

    if tier == "full-ci":
        if os.environ.get(QT_OPT_IN_ENV) != "1":
            raise ValueError(f"full-ci requires {QT_OPT_IN_ENV}=1")
        return [
            [str(python), str(AGENT_AUDIT)],
            [str(python), "-m", "ruff", "check", "."],
            [str(python), "-m", "pytest", "--allow-qt-tests", "-q"],
        ]

    commands: list[list[str]] = []
    if tier == "precommit":
        commands.append([str(python), str(AGENT_AUDIT)])
    else:
        commands.extend(
            [str(python), str(AGENT_AUDIT), "--check", check]
            for check in scope.audits
        )

    python_files = (
        tuple(sorted({path for path in changed if path.replace("\\", "/").endswith(".py")}))
        if tier == "precommit"
        else scope_python_files(scope, changed)
    )
    if python_files:
        commands.append([str(python), "-m", "ruff", "check", *python_files])
        commands.append([str(python), "-m", "py_compile", *python_files])
    if tier == "precommit" and scope.name == "repo":
        commands.append([str(python), "-m", "pytest", "-q"])
    elif scope.tests:
        commands.append([str(python), "-m", "pytest", *scope.tests, "-q"])
    return commands


def run_commands(commands: Sequence[Sequence[str]], *, list_only: bool) -> int:
    """Print commands and optionally execute them in order."""

    for command in commands:
        rendered = subprocess.list2cmdline(list(command))
        print(f"> {rendered}", flush=True)
        if list_only:
            continue
        result = subprocess.run(command, cwd=REPO_ROOT, check=False)
        if result.returncode:
            return int(result.returncode)
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    scopes, _registry = load_scopes()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=sorted(scopes))
    parser.add_argument(
        "--tier",
        choices=("focused", "precommit", "full-ci"),
        default="focused",
    )
    parser.add_argument("--list", action="store_true", help="Print commands without running them.")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate verification paths and local-safe test bundles, then exit.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    scopes, registry = load_scopes()
    args = parse_args(argv)
    errors = validate_config(scopes, registry)
    if errors:
        for error in errors:
            print(f"verification config error: {error}", file=sys.stderr)
        return 2
    if args.check_config:
        print(f"Verification config passed: {len(scopes)} scopes")
        return 0
    if args.scope is None:
        print("--scope is required unless --check-config is used", file=sys.stderr)
        return 2

    python = resolve_repo_python()
    scope = scopes[args.scope]
    print(f"Verification interpreter: {python}")
    try:
        commands = build_commands(
            scope,
            tier=args.tier,
            python=python,
            changed=changed_files(),
        )
    except (RuntimeError, ValueError) as exc:
        print(f"verification error: {exc}", file=sys.stderr)
        return 2
    result = run_commands(commands, list_only=args.list)
    if scope.manual_smoke:
        print("Manual/visible smoke path:")
        for step in scope.manual_smoke:
            print(f"- {step}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
