"""Command-line entry point for Free Harmonic Clustering Analysis."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Sequence

from .api import run_free_harmonic_clustering
from .models import (
    AnalysisDesign,
    FreeHarmonicError,
    FreeHarmonicMethodSpec,
    NoHarmonicsSelectedError,
    ProjectContrastRequest,
)


def _add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Validate and prepare tensors without writing any files.",
    )
    parser.add_argument(
        "--n-permutations",
        type=int,
        default=10_000,
        help="Whole-participant random assignments (default: 10000).",
    )
    parser.add_argument("--seed", type=int, default=1729, help="Random seed.")
    parser.add_argument(
        "--oddball-frequency-hz",
        type=float,
        default=1.2,
        help="Experiment oddball frequency in Hz (default: 1.2).",
    )
    parser.add_argument(
        "--base-frequency-hz",
        type=float,
        default=6.0,
        help="Experiment base-stimulation frequency in Hz (default: 6.0).",
    )
    parser.add_argument(
        "--max-harmonic-hz",
        type=float,
        default=48.0,
        help="Maximum oddball-harmonic frequency considered (default: 48).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=256,
        help="Permutation t-map batch size.",
    )
    parser.add_argument(
        "--run-id",
        help="Optional unique run directory name.",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        help=(
            "Optional final run directory beneath the managed project root; "
            "its name must match --run-id when both are supplied."
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m Tools.Free_Harmonic_Clustering",
        description=(
            "Run one headless, cluster-level Free Harmonic Clustering Analysis contrast from managed FPVS workbooks."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    independent = subparsers.add_parser(
        "independent",
        help="Compare two canonical project groups within one condition.",
    )
    independent.add_argument("--project-root", type=Path, required=True)
    independent.add_argument("--condition", required=True)
    independent.add_argument("--group-a", required=True)
    independent.add_argument("--group-b", required=True)
    _add_run_options(independent)

    paired = subparsers.add_parser(
        "paired",
        help="Compare two conditions in their complete paired participant cohort.",
    )
    paired.add_argument("--project-root", type=Path, required=True)
    paired.add_argument("--condition-a", required=True)
    paired.add_argument("--condition-b", required=True)
    paired.add_argument(
        "--group",
        help="Optional canonical group filter for the paired cohort.",
    )
    _add_run_options(paired)
    return parser


def _request_from_args(args: argparse.Namespace) -> ProjectContrastRequest:
    if args.command == "independent":
        return ProjectContrastRequest(
            project_root=args.project_root,
            design=AnalysisDesign.INDEPENDENT_GROUPS,
            condition_a=args.condition,
            group_ids=(args.group_a, args.group_b),
        )
    group_ids = () if args.group in (None, "") else (args.group,)
    return ProjectContrastRequest(
        project_root=args.project_root,
        design=AnalysisDesign.PAIRED_CONDITIONS,
        condition_a=args.condition_a,
        condition_b=args.condition_b,
        group_ids=group_ids,
    )


def _summary_payload(run: object) -> dict[str, object]:
    prepared = run.prepared
    payload: dict[str, object] = {
        "status": "prepared" if run.prepare_only else "complete",
        "design": prepared.request.design.value,
        "arm_a_label": prepared.arm_a_label,
        "arm_b_label": prepared.arm_b_label,
        "participant_count_a": len(prepared.participant_ids_a),
        "participant_count_b": len(prepared.participant_ids_b),
        "sensor_count": len(prepared.sensor_names),
        "retained_harmonic_count": len(prepared.harmonics_hz),
        "prepare_only": run.prepare_only,
        "write_performed": run.receipt is not None,
        "familywise_error_control": "weak-FWER",
        "validation_label": "paper-faithful-not-author-validated",
    }
    if run.receipt is not None:
        payload["output_directory"] = str(run.receipt.output_directory)
        payload["manifest_path"] = str(run.receipt.manifest_path)
    return payload


def _no_harmonics_diagnostic(
    error: NoHarmonicsSelectedError,
) -> dict[str, object]:
    def arm_max(values: object) -> dict[str, object] | None:
        z_values = [float(value) for value in values]
        finite_indices = [index for index, value in enumerate(z_values) if math.isfinite(value)]
        if not finite_indices:
            return None
        index = max(finite_indices, key=z_values.__getitem__)
        return {
            "z": z_values[index],
            "harmonic_order": int(error.candidate_orders[index]),
            "harmonic_hz": float(error.candidate_harmonics_hz[index]),
        }

    return {
        "code": error.code,
        "threshold": error.z_threshold,
        "arm_a_max": arm_max(error.arm_a_z),
        "arm_b_max": arm_max(error.arm_b_z),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        request = _request_from_args(args)
        method = FreeHarmonicMethodSpec(
            oddball_frequency_hz=args.oddball_frequency_hz,
            base_frequency_hz=args.base_frequency_hz,
            max_harmonic_hz=args.max_harmonic_hz,
            n_permutations=args.n_permutations,
            seed=args.seed,
        )
        run = run_free_harmonic_clustering(
            request,
            method,
            prepare_only=args.prepare_only,
            run_id=args.run_id,
            destination=args.destination,
            batch_size=args.batch_size,
        )
    except NoHarmonicsSelectedError as exc:
        sys.stderr.write(
            json.dumps(
                _no_harmonics_diagnostic(exc),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        )
        return 2
    except (FreeHarmonicError, OSError, ValueError) as exc:
        sys.stderr.write(f"Free Harmonic Clustering Analysis failed: {exc}\n")
        return 2

    sys.stdout.write(
        json.dumps(
            _summary_payload(run),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
