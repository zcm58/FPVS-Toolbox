"""Helpers for treating the local Source Localization tree as optional."""

from __future__ import annotations

import importlib
import importlib.util
import logging
from types import ModuleType
from typing import Any

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

SOURCE_LOCALIZATION_PACKAGE = "quarantine.Tools.LORETA.SourceLocalization"
SOURCE_LOCALIZATION_RUNNER_MODULE = f"{SOURCE_LOCALIZATION_PACKAGE}.runner"
SOURCE_LOCALIZATION_SOURCE_MODEL_MODULE = f"{SOURCE_LOCALIZATION_PACKAGE}.source_model"
SOURCE_LOCALIZATION_DIALOG_ATTR = "SourceLocalizationDialog"

_UNAVAILABLE_MESSAGE = (
    "Source Localization is unavailable because the optional local package "
    "`src/quarantine` is not present in this installation."
)


class SourceLocalizationUnavailableError(ImportError):
    """Raised when the optional local Source Localization tree is unavailable."""

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
    """Return whether the optional local Source Localization package is importable."""

    try:
        return importlib.util.find_spec(SOURCE_LOCALIZATION_PACKAGE) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def get_eloreta_runner(operation: str = "source_localization_runner") -> ModuleType:
    """Import and return the optional eLORETA runner module."""

    return _import_optional_module(
        SOURCE_LOCALIZATION_RUNNER_MODULE,
        operation=operation,
    )


def get_source_model_module(operation: str = "source_localization_source_model") -> ModuleType:
    """Import and return the optional Source Localization model module."""

    return _import_optional_module(
        SOURCE_LOCALIZATION_SOURCE_MODEL_MODULE,
        operation=operation,
    )


def get_source_localization_dialog_class(
    operation: str = "source_localization_dialog",
) -> type[Any]:
    """Import and return the optional Source Localization dialog class."""

    try:
        module = importlib.import_module(SOURCE_LOCALIZATION_PACKAGE)
        return getattr(module, SOURCE_LOCALIZATION_DIALOG_ATTR)
    except (AttributeError, ImportError, ModuleNotFoundError) as exc:
        raise _unavailable_error(
            operation=operation,
            attempted_import=SOURCE_LOCALIZATION_PACKAGE,
            exception=exc,
        ) from exc


def _import_optional_module(module_name: str, *, operation: str) -> ModuleType:
    try:
        return importlib.import_module(module_name)
    except (ImportError, ModuleNotFoundError) as exc:
        raise _unavailable_error(
            operation=operation,
            attempted_import=module_name,
            exception=exc,
        ) from exc


def _unavailable_error(
    *,
    operation: str,
    attempted_import: str,
    exception: BaseException,
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
