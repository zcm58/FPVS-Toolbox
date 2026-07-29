"""Deterministic participant-level resampling sensitivities.

The helpers in this module operate on a complete participant-by-cell matrix.
That boundary is deliberate: a sign flip is shared by every cell belonging to
one participant, and a permuted group label moves every cell belonging to one
participant.  Both procedures use a single-step maximum absolute studentized
statistic to control the family-wise error rate across the declared cells.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product
from math import comb
from typing import Callable, Iterator, Sequence

import numpy as np
import pandas as pd

from Tools.Stats.analysis.inference_contracts import HarmonicProvenance


RESAMPLING_SCHEMA_VERSION = 1
DEFAULT_SEED = 1729
DEFAULT_RESAMPLES = 9999
DEFAULT_EXACT_ENUMERATION_LIMIT = 65_536
UNKNOWN_GROUP_VALUES = frozenset(
    {"", "unknown", "unassigned", "none", "nan", "missing"}
)


class ResamplingValidationError(ValueError):
    """Raised when the requested resampling design cannot be specified."""


@dataclass(frozen=True)
class ResamplingResult:
    """Workbook-ready resampling results and explicit run metadata."""

    results: pd.DataFrame
    metadata: pd.DataFrame

    def to_frames(self) -> dict[str, pd.DataFrame]:
        """Return copies suitable for additive workbook export."""

        return {
            "Resampling Cell Results": self.results.copy(),
            "Resampling Metadata": self.metadata.copy(),
        }


@dataclass(frozen=True)
class _PreparedMatrix:
    participants: tuple[object, ...]
    cells: tuple[tuple[object, ...], ...]
    values: np.ndarray


@dataclass(frozen=True)
class _DataProblem(Exception):
    code: str
    message: str


def _stable_key(value: object) -> tuple[str, str]:
    return type(value).__name__, str(value)


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(missing) if isinstance(missing, (bool, np.bool_)) else False


def _validate_common_arguments(
    data: pd.DataFrame,
    *,
    dv_col: str,
    subject_col: str,
    cell_cols: Sequence[str],
    n_resamples: int,
    seed: int,
    exact_enumeration_limit: int,
    alpha: float,
    extra_required: Sequence[str] = (),
) -> tuple[str, ...]:
    if not isinstance(data, pd.DataFrame):
        raise TypeError("data must be a pandas DataFrame.")
    normalized_cells = tuple(str(column) for column in cell_cols)
    if not normalized_cells:
        raise ResamplingValidationError("cell_cols must contain at least one column.")
    if len(set(normalized_cells)) != len(normalized_cells):
        raise ResamplingValidationError("cell_cols must not contain duplicate columns.")
    if subject_col in normalized_cells or dv_col in normalized_cells:
        raise ResamplingValidationError(
            "subject_col, dv_col, and cell_cols must identify distinct columns."
        )
    required = (dv_col, subject_col, *normalized_cells, *extra_required)
    missing = [column for column in required if column not in data.columns]
    if missing:
        raise ResamplingValidationError(f"Missing required columns: {missing}")
    if isinstance(n_resamples, (bool, np.bool_)) or int(n_resamples) != n_resamples:
        raise ResamplingValidationError("n_resamples must be a positive integer.")
    if int(n_resamples) < 1:
        raise ResamplingValidationError("n_resamples must be a positive integer.")
    if isinstance(seed, (bool, np.bool_)) or int(seed) != seed or int(seed) < 0:
        raise ResamplingValidationError("seed must be a non-negative integer.")
    if (
        isinstance(exact_enumeration_limit, (bool, np.bool_))
        or int(exact_enumeration_limit) != exact_enumeration_limit
        or int(exact_enumeration_limit) < 1
    ):
        raise ResamplingValidationError(
            "exact_enumeration_limit must be a positive integer."
        )
    if not np.isfinite(float(alpha)) or not 0.0 < float(alpha) < 1.0:
        raise ResamplingValidationError("alpha must be strictly between 0 and 1.")
    return normalized_cells


def _observed_cells(
    data: pd.DataFrame,
    *,
    cell_cols: Sequence[str],
) -> tuple[tuple[object, ...], ...]:
    if data.empty:
        return ()
    cells: list[tuple[object, ...]] = []
    for values in data.loc[:, list(cell_cols)].itertuples(index=False, name=None):
        cell = tuple(values)
        if any(_is_missing(value) for value in cell):
            continue
        try:
            already_seen = cell in cells
        except (TypeError, ValueError):
            continue
        if not already_seen:
            cells.append(cell)
    return tuple(sorted(cells, key=lambda cell: tuple(_stable_key(value) for value in cell)))


def _prepare_complete_matrix(
    data: pd.DataFrame,
    *,
    dv_col: str,
    subject_col: str,
    cell_cols: Sequence[str],
) -> _PreparedMatrix:
    if data.empty:
        raise _DataProblem("empty_input", "No participant-cell rows were supplied.")

    participant_values = data[subject_col].tolist()
    if any(
        _is_missing(value)
        or isinstance(value, (bool, np.bool_))
        or (isinstance(value, str) and not value.strip())
        for value in participant_values
    ):
        raise _DataProblem(
            "invalid_participant_id",
            "Participant IDs must be non-missing, non-empty identifiers.",
        )
    cell_tuples = list(
        data.loc[:, list(cell_cols)].itertuples(index=False, name=None)
    )
    if any(
        _is_missing(value)
        or isinstance(value, (bool, np.bool_))
        or (isinstance(value, str) and not value.strip())
        for cell in cell_tuples
        for value in cell
    ):
        raise _DataProblem(
            "invalid_cell_identifier",
            "Every declared cell identifier must be non-missing and non-empty.",
        )

    try:
        grain = [
            (participant, *cell)
            for participant, cell in zip(participant_values, cell_tuples)
        ]
        if len(set(grain)) != len(grain):
            raise _DataProblem(
                "duplicate_participant_cell",
                "Each participant must contribute exactly one row to each declared cell.",
            )
        participants = tuple(sorted(set(participant_values), key=_stable_key))
        cells = tuple(
            sorted(
                set(cell_tuples),
                key=lambda cell: tuple(_stable_key(value) for value in cell),
            )
        )
    except TypeError as exc:
        raise _DataProblem(
            "unhashable_identifier",
            "Participant and cell identifiers must be scalar, hashable values.",
        ) from exc

    expected_grain = {
        (participant, *cell)
        for participant in participants
        for cell in cells
    }
    if set(grain) != expected_grain:
        raise _DataProblem(
            "incomplete_participant_cell_matrix",
            "Every participant must contribute every declared cell exactly once.",
        )

    raw_values = data[dv_col]
    boolean_mask = raw_values.map(lambda value: isinstance(value, (bool, np.bool_)))
    numeric = pd.to_numeric(raw_values, errors="coerce").astype(float)
    finite_mask = np.isfinite(numeric.to_numpy(dtype=float))
    if bool(boolean_mask.any()) or not bool(finite_mask.all()):
        raise _DataProblem(
            "nonfinite_or_invalid_response",
            "All response values must be numeric and finite before resampling.",
        )

    value_by_grain = {
        key: float(value)
        for key, value in zip(grain, numeric.to_numpy(dtype=float))
    }
    matrix = np.asarray(
        [
            [value_by_grain[(participant, *cell)] for cell in cells]
            for participant in participants
        ],
        dtype=float,
    )
    return _PreparedMatrix(
        participants=participants,
        cells=cells,
        values=matrix,
    )


def _selection_metadata(
    harmonic_provenance: HarmonicProvenance | str,
    *,
    selection_nesting_attested: bool,
) -> dict[str, object]:
    provenance = HarmonicProvenance.coerce(harmonic_provenance)
    if not isinstance(selection_nesting_attested, (bool, np.bool_)):
        raise ResamplingValidationError(
            "selection_nesting_attested must be a boolean."
        )
    nesting = bool(selection_nesting_attested)
    warning = ""
    if provenance is HarmonicProvenance.SAME_SAMPLE_ADAPTIVE:
        boundary = "exploratory_post_selection"
        role = "exploratory_sensitivity"
        warning = (
            "The harmonic range was selected from this sample. This matrix-level "
            "helper does not recompute harmonic selection inside each resample, "
            "so response inference remains exploratory."
        )
        if nesting:
            warning += (
                " A nesting attestation was recorded but cannot change that "
                "boundary without a selection-aware resampling callback."
            )
    elif provenance is HarmonicProvenance.INDEPENDENTLY_SELECTED:
        boundary = "independent_harmonic_selection"
        role = "sensitivity"
    elif provenance is HarmonicProvenance.USER_FIXED_UNVERIFIED:
        boundary = "harmonic_selection_independence_unverified"
        role = "exploratory_sensitivity"
    else:
        boundary = "harmonic_selection_unknown"
        role = "exploratory_sensitivity"
    return {
        "harmonic_provenance": provenance.value,
        "selection_nesting_attested": nesting,
        "selection_nesting_effective": False,
        "selection_boundary_status": boundary,
        "interpretation_role": role,
        "selection_warning": warning,
    }


def _metadata_frame(
    *,
    method: str,
    overall_status: str,
    status_code: str,
    status_message: str,
    seed: int,
    requested_draws: int,
    completed_draws: int,
    resampling_mode: str,
    total_unique_transformations: int | None,
    null_statistic_definition: str,
    family_id: str,
    family_label: str,
    family_size: int,
    alpha: float,
    p_value_count_convention: str,
    selection: dict[str, object],
) -> pd.DataFrame:
    if method == "participant_sign_flip_max_abs_t":
        randomization_assumption = (
            "Under the tested global null, each participant's complete "
            "Condition x ROI response vector is jointly sign-symmetric."
        )
    else:
        randomization_assumption = (
            "Under the tested global null, complete participant response "
            "vectors are exchangeable between the selected groups. For "
            "observational groups this requires comparable distributions "
            "apart from the group labels being tested."
        )
    return pd.DataFrame(
        [
            {
                "resampling_schema_version": RESAMPLING_SCHEMA_VERSION,
                "method": method,
                "overall_status": overall_status,
                "status_code": status_code,
                "status_message": status_message,
                "seed": int(seed),
                "draws_requested": int(requested_draws),
                "draws_completed": int(completed_draws),
                "resampling_mode": resampling_mode,
                "exact_enumeration": resampling_mode == "exact",
                "exactness_note": (
                    "Exact means every allowed transformation was enumerated; "
                    "it does not remove the randomization/exchangeability assumption."
                ),
                "total_unique_transformations": total_unique_transformations,
                "null_statistic_definition": null_statistic_definition,
                "randomization_assumption": randomization_assumption,
                "multiplicity_family_id": family_id,
                "multiplicity_family_label": family_label,
                "family_size": int(family_size),
                "multiplicity_adjustment": "single_step_max_abs_t_fwer",
                "p_value_count_convention": p_value_count_convention,
                "alpha": float(alpha),
                "automatic_test_switching": False,
                **selection,
            }
        ]
    )


def _failure_result(
    data: pd.DataFrame,
    *,
    cell_cols: Sequence[str],
    method: str,
    code: str,
    message: str,
    seed: int,
    requested_draws: int,
    null_statistic_definition: str,
    family_id: str,
    family_label: str,
    alpha: float,
    selection: dict[str, object],
    result_defaults: dict[str, object] | None = None,
) -> ResamplingResult:
    cells = _observed_cells(data, cell_cols=cell_cols) or (
        tuple(None for _ in cell_cols),
    )
    rows: list[dict[str, object]] = []
    for cell in cells:
        row = {column: value for column, value in zip(cell_cols, cell)}
        row.update(result_defaults or {})
        row.update(
            {
                "estimate": np.nan,
                "statistic": np.nan,
                "statistic_name": "t",
                "p_raw_resampling": np.nan,
                "p_adjusted_max_t": np.nan,
                "reject_adjusted": False,
                "raw_exceedances": 0,
                "max_t_exceedances": 0,
                "inference_status": "not_estimable",
                "status_code": code,
                "family_id": family_id,
                "family_label": family_label,
                "family_size": 0,
                "adjustment_method": "single_step_max_abs_t_fwer",
                "alpha": float(alpha),
                "interpretation_role": selection["interpretation_role"],
            }
        )
        rows.append(row)
    results = pd.DataFrame(rows)
    metadata = _metadata_frame(
        method=method,
        overall_status="not_estimable",
        status_code=code,
        status_message=message,
        seed=seed,
        requested_draws=requested_draws,
        completed_draws=0,
        resampling_mode="not_run",
        total_unique_transformations=None,
        null_statistic_definition=null_statistic_definition,
        family_id=family_id,
        family_label=family_label,
        family_size=0,
        alpha=alpha,
        p_value_count_convention="not_applicable",
        selection=selection,
    )
    return ResamplingResult(results=results, metadata=metadata)


def _studentized_one_sample(values: np.ndarray) -> np.ndarray:
    means = np.mean(values, axis=0)
    if values.shape[0] < 2:
        return np.full(values.shape[1], np.nan, dtype=float)
    standard_errors = np.std(values, axis=0, ddof=1) / np.sqrt(values.shape[0])
    statistics = np.zeros(values.shape[1], dtype=float)
    positive = standard_errors > 0.0
    statistics[positive] = means[positive] / standard_errors[positive]
    zero_with_signal = ~positive & (means != 0.0)
    statistics[zero_with_signal] = np.copysign(np.inf, means[zero_with_signal])
    statistics[~np.isfinite(standard_errors)] = np.nan
    return statistics


def _studentized_welch(
    values: np.ndarray,
    group_a_mask: np.ndarray,
) -> np.ndarray:
    values_a = values[group_a_mask]
    values_b = values[~group_a_mask]
    if values_a.shape[0] < 2 or values_b.shape[0] < 2:
        return np.full(values.shape[1], np.nan, dtype=float)
    means_a = np.mean(values_a, axis=0)
    means_b = np.mean(values_b, axis=0)
    difference = means_a - means_b
    variance_a = np.var(values_a, axis=0, ddof=1)
    variance_b = np.var(values_b, axis=0, ddof=1)
    standard_errors = np.sqrt(
        variance_a / values_a.shape[0] + variance_b / values_b.shape[0]
    )
    statistics = np.zeros(values.shape[1], dtype=float)
    positive = standard_errors > 0.0
    statistics[positive] = difference[positive] / standard_errors[positive]
    zero_with_signal = ~positive & (difference != 0.0)
    statistics[zero_with_signal] = np.copysign(
        np.inf,
        difference[zero_with_signal],
    )
    statistics[~np.isfinite(standard_errors)] = np.nan
    return statistics


def _count_null_exceedances(
    observed_abs: np.ndarray,
    null_statistics: Iterator[np.ndarray],
    *,
    planned_draws: int,
    cancel_check: Callable[[], bool] | None,
    progress_callback: Callable[[int, int], None] | None,
) -> tuple[np.ndarray, np.ndarray, int, bool]:
    raw_counts = np.zeros(observed_abs.size, dtype=np.int64)
    max_counts = np.zeros(observed_abs.size, dtype=np.int64)
    completed = 0
    while True:
        if cancel_check is not None and bool(cancel_check()):
            return raw_counts, max_counts, completed, True
        try:
            statistic = next(null_statistics)
        except StopIteration:
            break
        absolute = np.abs(np.asarray(statistic, dtype=float))
        finite_or_infinite = ~np.isnan(absolute)
        comparable = np.where(finite_or_infinite, absolute, -np.inf)
        raw_counts += comparable >= observed_abs
        null_max = float(np.max(comparable))
        max_counts += null_max >= observed_abs
        completed += 1
        if progress_callback is not None:
            progress_callback(completed, planned_draws)
    return raw_counts, max_counts, completed, False


def _resampling_p_values(
    counts: np.ndarray,
    *,
    completed: int,
    exact: bool,
) -> np.ndarray:
    if completed < 1:
        return np.full(counts.size, np.nan, dtype=float)
    if exact:
        return counts.astype(float) / completed
    return (counts.astype(float) + 1.0) / (completed + 1.0)


def _one_sample_null_statistics_exact(
    matrix: np.ndarray,
) -> Iterator[np.ndarray]:
    for signs in product((-1.0, 1.0), repeat=matrix.shape[0]):
        yield _studentized_one_sample(
            matrix * np.asarray(signs, dtype=float)[:, np.newaxis]
        )


def _one_sample_null_statistics_mc(
    matrix: np.ndarray,
    *,
    n_resamples: int,
    seed: int,
) -> Iterator[np.ndarray]:
    rng = np.random.default_rng(seed)
    for _ in range(n_resamples):
        signs = rng.choice((-1.0, 1.0), size=matrix.shape[0])
        yield _studentized_one_sample(matrix * signs[:, np.newaxis])


def run_one_sample_sign_flip_max_t(
    data: pd.DataFrame,
    *,
    dv_col: str,
    subject_col: str,
    cell_cols: Sequence[str] = ("condition", "roi"),
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
    exact_enumeration_limit: int = DEFAULT_EXACT_ENUMERATION_LIMIT,
    family_id: str = "one_sample_response_cells",
    family_label: str = "One-sample response contrasts across declared cells",
    alpha: float = 0.05,
    harmonic_provenance: HarmonicProvenance | str = HarmonicProvenance.UNKNOWN,
    selection_nesting_attested: bool = False,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> ResamplingResult:
    """Run a participant-wise sign-flip max-|t| sensitivity.

    Exact enumeration is used whenever all ``2**N`` participant sign patterns
    fit within ``exact_enumeration_limit``.  Otherwise, ``n_resamples`` joint
    row-wise sign patterns are sampled with a deterministic NumPy generator.
    """

    cells = _validate_common_arguments(
        data,
        dv_col=dv_col,
        subject_col=subject_col,
        cell_cols=cell_cols,
        n_resamples=n_resamples,
        seed=seed,
        exact_enumeration_limit=exact_enumeration_limit,
        alpha=alpha,
    )
    if not str(family_id).strip() or not str(family_label).strip():
        raise ResamplingValidationError("family_id and family_label must be non-empty.")
    selection = _selection_metadata(
        harmonic_provenance,
        selection_nesting_attested=selection_nesting_attested,
    )
    method = "participant_sign_flip_max_abs_t"
    null_definition = (
        "maximum absolute one-sample t across estimable declared cells; "
        "one shared sign per participant across the entire cell row"
    )
    try:
        prepared = _prepare_complete_matrix(
            data,
            dv_col=dv_col,
            subject_col=subject_col,
            cell_cols=cells,
        )
    except _DataProblem as problem:
        return _failure_result(
            data,
            cell_cols=cells,
            method=method,
            code=problem.code,
            message=problem.message,
            seed=int(seed),
            requested_draws=int(n_resamples),
            null_statistic_definition=null_definition,
            family_id=str(family_id).strip(),
            family_label=str(family_label).strip(),
            alpha=float(alpha),
            selection=selection,
            result_defaults={"n_participants": data[subject_col].nunique(dropna=True)},
        )

    matrix = prepared.values
    n_participants = matrix.shape[0]
    means = np.mean(matrix, axis=0)
    sample_sd = (
        np.std(matrix, axis=0, ddof=1)
        if n_participants >= 2
        else np.full(matrix.shape[1], np.nan)
    )
    observed = _studentized_one_sample(matrix)
    estimable = (
        (n_participants >= 2)
        & np.isfinite(sample_sd)
        & (sample_sd > 0.0)
        & np.isfinite(observed)
    )

    result_rows: list[dict[str, object]] = []
    for index, cell in enumerate(prepared.cells):
        if n_participants < 2:
            status_code = "tiny_n"
        elif not np.isfinite(sample_sd[index]) or sample_sd[index] <= 0.0:
            status_code = "zero_or_invalid_variance"
        elif not np.isfinite(observed[index]):
            status_code = "invalid_observed_statistic"
        else:
            status_code = "ok"
        row = {column: value for column, value in zip(cells, cell)}
        row.update(
            {
                "n_participants": n_participants,
                "estimate": float(means[index]),
                "sample_sd": float(sample_sd[index]),
                "statistic": (
                    float(observed[index]) if estimable[index] else np.nan
                ),
                "statistic_name": "one_sample_t",
                "p_raw_resampling": np.nan,
                "p_adjusted_max_t": np.nan,
                "reject_adjusted": False,
                "raw_exceedances": 0,
                "max_t_exceedances": 0,
                "inference_status": "estimated" if estimable[index] else "not_estimable",
                "status_code": status_code,
            }
        )
        result_rows.append(row)

    family_size = int(np.sum(estimable))
    if family_size == 0:
        results = pd.DataFrame(result_rows)
        for column, value in (
            ("family_id", family_id),
            ("family_label", family_label),
            ("family_size", 0),
            ("adjustment_method", "single_step_max_abs_t_fwer"),
            ("alpha", float(alpha)),
            ("interpretation_role", selection["interpretation_role"]),
        ):
            results[column] = value
        metadata = _metadata_frame(
            method=method,
            overall_status="not_estimable",
            status_code="no_estimable_cells",
            status_message="No declared cell had sufficient non-zero variance.",
            seed=int(seed),
            requested_draws=int(n_resamples),
            completed_draws=0,
            resampling_mode="not_run",
            total_unique_transformations=2**n_participants,
            null_statistic_definition=null_definition,
            family_id=str(family_id).strip(),
            family_label=str(family_label).strip(),
            family_size=0,
            alpha=float(alpha),
            p_value_count_convention="not_applicable",
            selection=selection,
        )
        return ResamplingResult(results=results, metadata=metadata)

    estimable_matrix = matrix[:, estimable]
    estimable_observed_abs = np.abs(observed[estimable])
    total_unique = 2**n_participants
    exact = total_unique <= int(exact_enumeration_limit)
    if exact:
        null_iterator = _one_sample_null_statistics_exact(estimable_matrix)
    else:
        null_iterator = _one_sample_null_statistics_mc(
            estimable_matrix,
            n_resamples=int(n_resamples),
            seed=int(seed),
        )
    planned_draws = total_unique if exact else int(n_resamples)
    raw_counts, max_counts, completed, cancelled = _count_null_exceedances(
        estimable_observed_abs,
        null_iterator,
        planned_draws=planned_draws,
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )
    if cancelled:
        estimable_index = 0
        for index, is_estimable in enumerate(estimable):
            if not is_estimable:
                continue
            result_rows[index].update(
                {
                    "raw_exceedances": int(raw_counts[estimable_index]),
                    "max_t_exceedances": int(max_counts[estimable_index]),
                    "inference_status": "cancelled",
                    "status_code": "cancelled",
                }
            )
            estimable_index += 1
        results = pd.DataFrame(result_rows)
        for column, value in (
            ("family_id", str(family_id).strip()),
            ("family_label", str(family_label).strip()),
            ("family_size", family_size),
            ("adjustment_method", "single_step_max_abs_t_fwer"),
            ("alpha", float(alpha)),
            ("interpretation_role", selection["interpretation_role"]),
        ):
            results[column] = value
        metadata = _metadata_frame(
            method=method,
            overall_status="cancelled",
            status_code="cancelled",
            status_message=(
                "Resampling was cancelled; partial exceedance counts are not "
                "reported as inferential p-values."
            ),
            seed=int(seed),
            requested_draws=int(n_resamples),
            completed_draws=completed,
            resampling_mode="exact" if exact else "monte_carlo",
            total_unique_transformations=total_unique,
            null_statistic_definition=null_definition,
            family_id=str(family_id).strip(),
            family_label=str(family_label).strip(),
            family_size=family_size,
            alpha=float(alpha),
            p_value_count_convention="not_computed_cancelled",
            selection=selection,
        )
        return ResamplingResult(results=results, metadata=metadata)
    p_raw = _resampling_p_values(raw_counts, completed=completed, exact=exact)
    p_adjusted = _resampling_p_values(max_counts, completed=completed, exact=exact)

    estimable_index = 0
    for index, is_estimable in enumerate(estimable):
        if not is_estimable:
            continue
        result_rows[index].update(
            {
                "p_raw_resampling": float(p_raw[estimable_index]),
                "p_adjusted_max_t": float(p_adjusted[estimable_index]),
                "reject_adjusted": bool(p_adjusted[estimable_index] <= alpha),
                "raw_exceedances": int(raw_counts[estimable_index]),
                "max_t_exceedances": int(max_counts[estimable_index]),
            }
        )
        estimable_index += 1

    results = pd.DataFrame(result_rows)
    for column, value in (
        ("family_id", str(family_id).strip()),
        ("family_label", str(family_label).strip()),
        ("family_size", family_size),
        ("adjustment_method", "single_step_max_abs_t_fwer"),
        ("alpha", float(alpha)),
        ("interpretation_role", selection["interpretation_role"]),
    ):
        results[column] = value
    p_convention = (
        "exact exceedance count divided by all unique sign patterns"
        if exact
        else "Monte Carlo plus-one: (1 + exceedances) / (draws_completed + 1)"
    )
    partial = family_size != len(result_rows)
    metadata = _metadata_frame(
        method=method,
        overall_status="estimated_with_nonestimable_cells" if partial else "estimated",
        status_code="partial_family" if partial else "ok",
        status_message=(
            "Maximum-statistic p-values were computed across estimable cells only."
            if partial
            else "Maximum-statistic p-values were computed across all declared cells."
        ),
        seed=int(seed),
        requested_draws=int(n_resamples),
        completed_draws=completed,
        resampling_mode="exact" if exact else "monte_carlo",
        total_unique_transformations=total_unique,
        null_statistic_definition=null_definition,
        family_id=str(family_id).strip(),
        family_label=str(family_label).strip(),
        family_size=family_size,
        alpha=float(alpha),
        p_value_count_convention=p_convention,
        selection=selection,
    )
    return ResamplingResult(results=results, metadata=metadata)


def _normalize_group(value: object) -> str:
    if _is_missing(value):
        return ""
    normalized = str(value).strip()
    if normalized.casefold() in UNKNOWN_GROUP_VALUES:
        return ""
    return normalized


def _participant_groups(
    data: pd.DataFrame,
    *,
    subject_col: str,
    group_col: str,
) -> tuple[dict[object, str], tuple[str, ...]]:
    assignments: dict[object, str] = {}
    display_by_key: dict[str, str] = {}
    for participant, rows in data.groupby(subject_col, dropna=False, sort=False):
        if _is_missing(participant) or (
            isinstance(participant, str) and not participant.strip()
        ):
            raise _DataProblem(
                "invalid_participant_id",
                "Participant IDs must be non-missing and non-empty.",
            )
        labels = [_normalize_group(value) for value in rows[group_col]]
        if any(not label for label in labels):
            raise _DataProblem(
                "invalid_group_assignment",
                "Every participant must have a non-missing canonical group ID.",
            )
        label_keys = {label.casefold() for label in labels}
        if len(label_keys) != 1:
            raise _DataProblem(
                "inconsistent_group_assignment",
                "Each participant must have one canonical group ID.",
            )
        label = labels[0]
        key = label.casefold()
        display_by_key.setdefault(key, label)
        assignments[participant] = display_by_key[key]
    groups = tuple(
        display_by_key[key] for key in sorted(display_by_key, key=str.casefold)
    )
    return assignments, groups


def _resolve_group_pair(
    groups: Sequence[str],
    group_pair: Sequence[object] | None,
) -> tuple[str, str]:
    by_key = {group.casefold(): group for group in groups}
    if group_pair is None:
        if len(groups) != 2:
            raise _DataProblem(
                "unsupported_group_count",
                "Exactly two groups are required unless group_pair selects two groups.",
            )
        return groups[0], groups[1]
    if len(group_pair) != 2:
        raise ResamplingValidationError(
            "group_pair must contain exactly two distinct group IDs."
        )
    requested = tuple(_normalize_group(value) for value in group_pair)
    if (
        not all(requested)
        or requested[0].casefold() == requested[1].casefold()
    ):
        raise ResamplingValidationError(
            "group_pair must contain exactly two distinct group IDs."
        )
    missing = [group for group in requested if group.casefold() not in by_key]
    if missing:
        raise _DataProblem(
            "selected_group_missing",
            "Selected group IDs are not present: " + ", ".join(missing),
        )
    return by_key[requested[0].casefold()], by_key[requested[1].casefold()]


def _group_null_statistics_exact(
    matrix: np.ndarray,
    *,
    n_group_a: int,
) -> Iterator[np.ndarray]:
    for indices in combinations(range(matrix.shape[0]), n_group_a):
        mask = np.zeros(matrix.shape[0], dtype=bool)
        mask[list(indices)] = True
        yield _studentized_welch(matrix, mask)


def _group_null_statistics_mc(
    matrix: np.ndarray,
    *,
    n_group_a: int,
    n_resamples: int,
    seed: int,
) -> Iterator[np.ndarray]:
    rng = np.random.default_rng(seed)
    for _ in range(n_resamples):
        indices = rng.choice(matrix.shape[0], size=n_group_a, replace=False)
        mask = np.zeros(matrix.shape[0], dtype=bool)
        mask[indices] = True
        yield _studentized_welch(matrix, mask)


def run_group_label_permutation_max_t(
    data: pd.DataFrame,
    *,
    dv_col: str,
    subject_col: str,
    group_col: str,
    cell_cols: Sequence[str] = ("condition", "roi"),
    group_pair: Sequence[object] | None = None,
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
    exact_enumeration_limit: int = DEFAULT_EXACT_ENUMERATION_LIMIT,
    family_id: str = "between_group_cells",
    family_label: str = "Between-group contrasts across declared cells",
    alpha: float = 0.05,
    harmonic_provenance: HarmonicProvenance | str = HarmonicProvenance.UNKNOWN,
    selection_nesting_attested: bool = False,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> ResamplingResult:
    """Run participant-label permutation max-|Welch t| sensitivity."""

    cells = _validate_common_arguments(
        data,
        dv_col=dv_col,
        subject_col=subject_col,
        cell_cols=cell_cols,
        n_resamples=n_resamples,
        seed=seed,
        exact_enumeration_limit=exact_enumeration_limit,
        alpha=alpha,
        extra_required=(group_col,),
    )
    if group_col in cells or group_col in {dv_col, subject_col}:
        raise ResamplingValidationError(
            "group_col must be distinct from subject_col, dv_col, and cell_cols."
        )
    if not str(family_id).strip() or not str(family_label).strip():
        raise ResamplingValidationError("family_id and family_label must be non-empty.")
    selection = _selection_metadata(
        harmonic_provenance,
        selection_nesting_attested=selection_nesting_attested,
    )
    method = "participant_group_label_permutation_max_abs_welch_t"
    null_definition = (
        "maximum absolute Welch t across estimable declared cells; one permuted "
        "group label per participant shared across the entire cell row"
    )
    try:
        assignments, groups = _participant_groups(
            data,
            subject_col=subject_col,
            group_col=group_col,
        )
        group_a, group_b = _resolve_group_pair(groups, group_pair)
        selected_participants = {
            participant
            for participant, group in assignments.items()
            if group.casefold() in {group_a.casefold(), group_b.casefold()}
        }
        working = data[data[subject_col].isin(selected_participants)].copy()
        prepared = _prepare_complete_matrix(
            working,
            dv_col=dv_col,
            subject_col=subject_col,
            cell_cols=cells,
        )
    except _DataProblem as problem:
        return _failure_result(
            data,
            cell_cols=cells,
            method=method,
            code=problem.code,
            message=problem.message,
            seed=int(seed),
            requested_draws=int(n_resamples),
            null_statistic_definition=null_definition,
            family_id=str(family_id).strip(),
            family_label=str(family_label).strip(),
            alpha=float(alpha),
            selection=selection,
            result_defaults={
                "group_a": None,
                "group_b": None,
                "n_group_a": 0,
                "n_group_b": 0,
            },
        )

    observed_group_a_mask = np.asarray(
        [
            assignments[participant].casefold() == group_a.casefold()
            for participant in prepared.participants
        ],
        dtype=bool,
    )
    n_group_a = int(np.sum(observed_group_a_mask))
    n_group_b = int(prepared.values.shape[0] - n_group_a)
    values_a = prepared.values[observed_group_a_mask]
    values_b = prepared.values[~observed_group_a_mask]
    mean_a = (
        np.mean(values_a, axis=0)
        if n_group_a
        else np.full(prepared.values.shape[1], np.nan)
    )
    mean_b = (
        np.mean(values_b, axis=0)
        if n_group_b
        else np.full(prepared.values.shape[1], np.nan)
    )
    sd_a = (
        np.std(values_a, axis=0, ddof=1)
        if n_group_a >= 2
        else np.full(prepared.values.shape[1], np.nan)
    )
    sd_b = (
        np.std(values_b, axis=0, ddof=1)
        if n_group_b >= 2
        else np.full(prepared.values.shape[1], np.nan)
    )
    observed = _studentized_welch(prepared.values, observed_group_a_mask)
    estimable = (
        (n_group_a >= 2)
        & (n_group_b >= 2)
        & np.isfinite(observed)
        & np.isfinite(sd_a)
        & np.isfinite(sd_b)
        & ((sd_a**2 / n_group_a + sd_b**2 / n_group_b) > 0.0)
    )

    result_rows: list[dict[str, object]] = []
    for index, cell in enumerate(prepared.cells):
        standard_error_squared = (
            sd_a[index] ** 2 / n_group_a + sd_b[index] ** 2 / n_group_b
            if n_group_a >= 2 and n_group_b >= 2
            else np.nan
        )
        if n_group_a < 2 or n_group_b < 2:
            status_code = "tiny_group_n"
        elif (
            not np.isfinite(standard_error_squared)
            or standard_error_squared <= 0.0
        ):
            status_code = "zero_or_invalid_standard_error"
        elif not np.isfinite(observed[index]):
            status_code = "invalid_observed_statistic"
        else:
            status_code = "ok"
        row = {column: value for column, value in zip(cells, cell)}
        row.update(
            {
                "group_a": group_a,
                "group_b": group_b,
                "n_group_a": n_group_a,
                "n_group_b": n_group_b,
                "mean_group_a": float(mean_a[index]),
                "mean_group_b": float(mean_b[index]),
                "estimate": float(mean_a[index] - mean_b[index]),
                "sd_group_a": float(sd_a[index]),
                "sd_group_b": float(sd_b[index]),
                "statistic": (
                    float(observed[index]) if estimable[index] else np.nan
                ),
                "statistic_name": "welch_t",
                "p_raw_resampling": np.nan,
                "p_adjusted_max_t": np.nan,
                "reject_adjusted": False,
                "raw_exceedances": 0,
                "max_t_exceedances": 0,
                "inference_status": "estimated" if estimable[index] else "not_estimable",
                "status_code": status_code,
            }
        )
        result_rows.append(row)

    family_size = int(np.sum(estimable))
    total_unique = comb(n_group_a + n_group_b, n_group_a)
    if family_size == 0:
        results = pd.DataFrame(result_rows)
        for column, value in (
            ("family_id", family_id),
            ("family_label", family_label),
            ("family_size", 0),
            ("adjustment_method", "single_step_max_abs_t_fwer"),
            ("alpha", float(alpha)),
            ("interpretation_role", selection["interpretation_role"]),
        ):
            results[column] = value
        metadata = _metadata_frame(
            method=method,
            overall_status="not_estimable",
            status_code="no_estimable_cells",
            status_message="No declared cell had two groups with a finite standard error.",
            seed=int(seed),
            requested_draws=int(n_resamples),
            completed_draws=0,
            resampling_mode="not_run",
            total_unique_transformations=total_unique,
            null_statistic_definition=null_definition,
            family_id=str(family_id).strip(),
            family_label=str(family_label).strip(),
            family_size=0,
            alpha=float(alpha),
            p_value_count_convention="not_applicable",
            selection=selection,
        )
        return ResamplingResult(results=results, metadata=metadata)

    estimable_matrix = prepared.values[:, estimable]
    estimable_observed_abs = np.abs(observed[estimable])
    exact = total_unique <= int(exact_enumeration_limit)
    if exact:
        null_iterator = _group_null_statistics_exact(
            estimable_matrix,
            n_group_a=n_group_a,
        )
    else:
        null_iterator = _group_null_statistics_mc(
            estimable_matrix,
            n_group_a=n_group_a,
            n_resamples=int(n_resamples),
            seed=int(seed),
        )
    planned_draws = total_unique if exact else int(n_resamples)
    raw_counts, max_counts, completed, cancelled = _count_null_exceedances(
        estimable_observed_abs,
        null_iterator,
        planned_draws=planned_draws,
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )
    if cancelled:
        estimable_index = 0
        for index, is_estimable in enumerate(estimable):
            if not is_estimable:
                continue
            result_rows[index].update(
                {
                    "raw_exceedances": int(raw_counts[estimable_index]),
                    "max_t_exceedances": int(max_counts[estimable_index]),
                    "inference_status": "cancelled",
                    "status_code": "cancelled",
                }
            )
            estimable_index += 1
        results = pd.DataFrame(result_rows)
        for column, value in (
            ("family_id", str(family_id).strip()),
            ("family_label", str(family_label).strip()),
            ("family_size", family_size),
            ("adjustment_method", "single_step_max_abs_t_fwer"),
            ("alpha", float(alpha)),
            ("interpretation_role", selection["interpretation_role"]),
        ):
            results[column] = value
        metadata = _metadata_frame(
            method=method,
            overall_status="cancelled",
            status_code="cancelled",
            status_message=(
                "Resampling was cancelled; partial exceedance counts are not "
                "reported as inferential p-values."
            ),
            seed=int(seed),
            requested_draws=int(n_resamples),
            completed_draws=completed,
            resampling_mode="exact" if exact else "monte_carlo",
            total_unique_transformations=total_unique,
            null_statistic_definition=null_definition,
            family_id=str(family_id).strip(),
            family_label=str(family_label).strip(),
            family_size=family_size,
            alpha=float(alpha),
            p_value_count_convention="not_computed_cancelled",
            selection=selection,
        )
        return ResamplingResult(results=results, metadata=metadata)
    p_raw = _resampling_p_values(raw_counts, completed=completed, exact=exact)
    p_adjusted = _resampling_p_values(max_counts, completed=completed, exact=exact)

    estimable_index = 0
    for index, is_estimable in enumerate(estimable):
        if not is_estimable:
            continue
        result_rows[index].update(
            {
                "p_raw_resampling": float(p_raw[estimable_index]),
                "p_adjusted_max_t": float(p_adjusted[estimable_index]),
                "reject_adjusted": bool(p_adjusted[estimable_index] <= alpha),
                "raw_exceedances": int(raw_counts[estimable_index]),
                "max_t_exceedances": int(max_counts[estimable_index]),
            }
        )
        estimable_index += 1

    results = pd.DataFrame(result_rows)
    for column, value in (
        ("family_id", str(family_id).strip()),
        ("family_label", str(family_label).strip()),
        ("family_size", family_size),
        ("adjustment_method", "single_step_max_abs_t_fwer"),
        ("alpha", float(alpha)),
        ("interpretation_role", selection["interpretation_role"]),
    ):
        results[column] = value
    p_convention = (
        "exact exceedance count divided by all unique participant label assignments"
        if exact
        else "Monte Carlo plus-one: (1 + exceedances) / (draws_completed + 1)"
    )
    partial = family_size != len(result_rows)
    metadata = _metadata_frame(
        method=method,
        overall_status="estimated_with_nonestimable_cells" if partial else "estimated",
        status_code="partial_family" if partial else "ok",
        status_message=(
            "Maximum-statistic p-values were computed across estimable cells only."
            if partial
            else "Maximum-statistic p-values were computed across all declared cells."
        ),
        seed=int(seed),
        requested_draws=int(n_resamples),
        completed_draws=completed,
        resampling_mode="exact" if exact else "monte_carlo",
        total_unique_transformations=total_unique,
        null_statistic_definition=null_definition,
        family_id=str(family_id).strip(),
        family_label=str(family_label).strip(),
        family_size=family_size,
        alpha=float(alpha),
        p_value_count_convention=p_convention,
        selection=selection,
    )
    return ResamplingResult(results=results, metadata=metadata)


__all__ = [
    "DEFAULT_EXACT_ENUMERATION_LIMIT",
    "DEFAULT_RESAMPLES",
    "DEFAULT_SEED",
    "RESAMPLING_SCHEMA_VERSION",
    "ResamplingResult",
    "ResamplingValidationError",
    "UNKNOWN_GROUP_VALUES",
    "run_group_label_permutation_max_t",
    "run_one_sample_sign_flip_max_t",
]
