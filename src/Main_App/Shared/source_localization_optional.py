"""Helpers for treating Source Localization as quarantined dead code."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

SOURCE_LOCALIZATION_PACKAGE = "quarantine.Tools.LORETA.SourceLocalization"
SOURCE_LOCALIZATION_RUNNER_MODULE = f"{SOURCE_LOCALIZATION_PACKAGE}.runner"
SOURCE_LOCALIZATION_SOURCE_MODEL_MODULE = f"{SOURCE_LOCALIZATION_PACKAGE}.source_model"
SOURCE_LOCALIZATION_DIALOG_ATTR = "SourceLocalizationDialog"

_UNAVAILABLE_MESSAGE = (
    "Source Localization is unavailable because the LORETA SourceLocalization "
    "tree is quarantined dead code and is not an active runtime feature."
)


class SourceLocalizationUnavailableError(ImportError):
    """Raised when Source Localization is unavailable because it is quarantined."""

    def __init__(
        self,
        *,
        operation: str,
        attempted_import: str,
        exception: BaseException | None = None,
    ) -> None:
        detail = _UNAVAILABLE_MESSAGE
        if exception is not None and str(exception):
            detail = f"{detail} Import error: {exception}"
        super().__init__(detail)
        self.operation = operation
        self.attempted_import = attempted_import
        self.exception_text = "" if exception is None else str(exception)
        self.optional_dependency_present = False
        self.user_message = _UNAVAILABLE_MESSAGE


def get_source_localization_unavailable_message() -> str:
    """Return the user-facing message for a missing optional dependency."""

    return _UNAVAILABLE_MESSAGE


def is_source_localization_available() -> bool:
    """Return whether Source Localization is available in active runtime."""

    return False


def get_eloreta_runner(operation: str = "source_localization_runner") -> Any:
    """Raise because Source Localization is quarantined dead code."""

    raise _unavailable_error(
        operation=operation,
        attempted_import=SOURCE_LOCALIZATION_RUNNER_MODULE,
        exception=None,
    )


def get_source_model_module(operation: str = "source_localization_source_model") -> Any:
    """Raise because Source Localization is quarantined dead code."""

    raise _unavailable_error(
        operation=operation,
        attempted_import=SOURCE_LOCALIZATION_SOURCE_MODEL_MODULE,
        exception=None,
    )


def get_source_localization_dialog_class(
    operation: str = "source_localization_dialog",
) -> type[Any]:
    """Raise because Source Localization is quarantined dead code."""

    raise _unavailable_error(
        operation=operation,
        attempted_import=SOURCE_LOCALIZATION_PACKAGE,
        exception=None,
    )


def _unavailable_error(
    *,
    operation: str,
    attempted_import: str,
    exception: BaseException | None,
) -> SourceLocalizationUnavailableError:
    err = SourceLocalizationUnavailableError(
        operation=operation,
        attempted_import=attempted_import,
        exception=exception,
    )
    logger.warning(
        "source_localization_unavailable operation=%s attempted_import=%s "
        "optional_dependency_present=%s exception=%s",
        err.operation,
        err.attempted_import,
        err.optional_dependency_present,
        err.exception_text,
        extra={
            "operation": err.operation,
            "attempted_import": err.attempted_import,
            "optional_dependency_present": err.optional_dependency_present,
            "exception_text": err.exception_text,
        },
    )
    return err
