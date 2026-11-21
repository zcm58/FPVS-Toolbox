"""Resource bounds imposed by this process's Linux cgroup hierarchy."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import re
import sys


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


def _mount_path(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), value)


def _controllers(proc: Path):
    memberships = {}
    for row in _text(proc / "cgroup").splitlines():
        parts = row.split(":", 2)
        if len(parts) == 3:
            for name in parts[1].split(","):
                memberships[name] = PurePosixPath(parts[2])
    for row in _text(proc / "mountinfo").splitlines():
        path_info, _, mount_info = row.partition(" - ")
        fields, filesystem = path_info.split(), mount_info.split()
        if len(fields) < 5 or len(filesystem) < 3 or filesystem[0] not in {"cgroup", "cgroup2"}:
            continue
        unified = filesystem[0] == "cgroup2"
        controllers = [""] if unified else filesystem[2].split(",")
        root = PurePosixPath(_mount_path(fields[3]))
        mount = Path(_mount_path(fields[4]))
        for controller in controllers:
            membership = memberships.get(controller)
            if controller not in {"", "cpu", "memory"} or membership is None or not membership.is_absolute():
                continue
            # Containers may expose the cgroup namespace root as "/" even when
            # mountinfo records its host path. Always check the visible mount.
            relative = membership.relative_to(root) if membership.is_relative_to(root) else membership.relative_to("/")
            if ".." in relative.parts:
                relative = PurePosixPath(".")
            current = mount.joinpath(*relative.parts)
            while True:
                yield controller, current
                if current == mount:
                    break
                current = current.parent


def cgroup_limits(proc: Path = Path("/proc/self")) -> tuple[int | None, int | None, int | None]:
    """Return finite CPU, memory and current memory-headroom limits, if present."""
    cpus, totals, free = [], [], []
    if sys.platform.startswith("linux"):
        for controller, directory in _controllers(proc):
            if controller in {"", "cpu"}:
                if controller == "":
                    quota_period = _text(directory / "cpu.max").split()
                else:
                    quota_period = [_text(directory / "cpu.cfs_quota_us"), _text(directory / "cpu.cfs_period_us")]
                if len(quota_period) == 2 and all(s.isdecimal() and int(s) > 0 for s in quota_period):
                    quota, period = map(int, quota_period)
                    cpus.append((quota + period - 1) // period)
            if controller in {"", "memory"}:
                limit_name, usage_name = (("memory.max", "memory.current") if controller == ""
                                          else ("memory.limit_in_bytes", "memory.usage_in_bytes"))
                limit = _text(directory / limit_name)
                if limit.isdecimal():
                    total = int(limit)
                    totals.append(total)
                    usage = _text(directory / usage_name)
                    if usage.isdecimal():
                        free.append(max(0, total - int(usage)))
    return min(cpus, default=None), min(totals, default=None), min(free, default=None)
