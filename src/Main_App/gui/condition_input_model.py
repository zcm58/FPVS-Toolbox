"""GUI-neutral validation for the editable condition rows."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from Main_App.projects import condition_output_folder_name


@dataclass(frozen=True)
class ConditionInputError:
    row: int
    field: str
    message: str


def validate_condition_rows(
    rows: Sequence[tuple[str, str]],
) -> tuple[dict[str, int], tuple[ConditionInputError, ...]]:
    """Validate the whole draft without dropping partial or duplicate entries."""
    mapping: dict[str, int] = {}
    errors: list[ConditionInputError] = []
    seen: dict[str, str] = {}
    for index, (raw_label, raw_id) in enumerate(rows):
        label, ident = raw_label.strip(), raw_id.strip()
        if not label and not ident:
            continue
        output_name = condition_output_folder_name(label)
        output_key = output_name.casefold()
        if not label:
            errors.append(ConditionInputError(index, "label", "Enter a condition name."))
        elif any(char in '<>:"/\\|?*' for char in label):
            errors.append(ConditionInputError(index, "label", "Remove file-name characters: < > : \" / \\ | ? *"))
        elif output_key in seen:
            errors.append(ConditionInputError(
                index, "label",
                f"Use a different condition name; output name {output_name!r} is "
                f"already used by {seen[output_key]!r} (ignoring case and numeric prefixes).",
            ))
        seen.setdefault(output_key, label)
        if not ident.isascii() or not ident.isdecimal() or not 1 <= int(ident) <= 999999:
            errors.append(ConditionInputError(index, "id", "Enter a recorded marker ID from 1 to 999999."))
        if not any(error.row == index for error in errors):
            mapping[label] = int(ident)
    return mapping, tuple(errors)
