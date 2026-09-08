"""Diagnostic-only per-audit-table exact text-frequency reuse.

No production edits. The traversal/error paths match frequency_domain_qc.
Only exact built-in str tokens of at most 128 code points are eligible; all
other values call the existing converter at the original point in row order.
At most 256 entries survive one table call. No source or validated evidence is
retained outside that call. This module neither reads project data nor executes
the candidate when imported.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager

from Main_App.processing import frequency_domain_qc as qc

MAX_TOKENS = 256
MAX_TOKEN_LENGTH = 128


def candidate_audit_rows(*, file_path, reader, log_func):
    from Main_App.io import MissingXlsxColumnsError

    try:
        frame = reader(
            file_path,
            sheet_name=qc.SPECTRAL_METRIC_QC_SHEET_NAME,
            required_columns=list(qc._BCA_AUDIT_REQUIRED_COLUMNS),
        )
    except MissingXlsxColumnsError as exc:
        log_func(
            "Frequency-domain QC ignored malformed optional spectral audit "
            f"metadata in {file_path}: {exc}"
        )
        return {}
    except (OSError, ValueError):
        return {}

    rows_by_cell = defaultdict(list)
    if frame.columns.is_unique:
        positions = frame.columns.get_indexer(qc._BCA_AUDIT_REQUIRED_COLUMNS)
        row_values = (
            tuple(values[position] if position >= 0 else None for position in positions)
            for values in frame.to_numpy(copy=False)
        )
    else:
        row_values = (
            tuple(row.get(column) for column in qc._BCA_AUDIT_REQUIRED_COLUMNS)
            for _, row in frame.iterrows()
        )
    frequency_columns = {}
    for raw_electrode, raw_frequency, raw_status, raw_reasons in row_values:
        electrode = qc._normalize_electrode(qc._optional_cell_text(raw_electrode))
        if type(raw_frequency) is str and len(raw_frequency) <= MAX_TOKEN_LENGTH:
            column = frequency_columns.get(raw_frequency)
            if column is None:
                column = qc._exact_frequency_column(raw_frequency)
                if len(frequency_columns) < MAX_TOKENS:
                    frequency_columns[raw_frequency] = column
        else:
            column = qc._exact_frequency_column(raw_frequency)
        if not electrode or not column:
            continue
        reason_codes = tuple(
            reason.strip()
            for reason in qc._optional_cell_text(raw_reasons).split(";")
            if reason.strip()
        )
        rows_by_cell[(electrode, column)].append({
            "bca_status": qc._optional_cell_text(raw_status).casefold(),
            "reason_codes": reason_codes,
        })
    return {key: tuple(value) for key, value in rows_by_cell.items()}


@contextmanager
def install():
    """Temporarily select this parser in one isolated single-thread benchmark."""
    original = qc._read_bca_method_audit_rows
    qc._read_bca_method_audit_rows = candidate_audit_rows
    try:
        yield candidate_audit_rows
    finally:
        qc._read_bca_method_audit_rows = original
