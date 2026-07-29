"""GUI-neutral contracts for statistical inference and result provenance."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Iterable

import pandas as pd


class _StringEnum(str, Enum):
    """String enum with a stable value-based coercion helper."""

    @classmethod
    def coerce(cls, value: "_StringEnum | str") -> "_StringEnum":
        if isinstance(value, cls):
            return value
        normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        for member in cls:
            if normalized in {member.value, member.name.lower()}:
                return member
        raise ValueError(
            f"Unknown {cls.__name__} value {value!r}; "
            f"expected one of: {', '.join(member.value for member in cls)}."
        )


class AnalysisProfile(_StringEnum):
    """High-level interpretation profile requested for an analysis run."""

    CONFIRMATORY = "confirmatory"
    PUBLISHED_STYLE_EXPLORATORY = "published_style_exploratory"


class HarmonicProvenance(_StringEnum):
    """How the harmonic list relates to the data currently being tested."""

    INDEPENDENTLY_SELECTED = "independently_selected"
    USER_FIXED_UNVERIFIED = "user_fixed_unverified"
    SAME_SAMPLE_ADAPTIVE = "same_sample_adaptive"
    UNKNOWN = "unknown"

    @property
    def independently_selected(self) -> bool:
        """Return whether the selection is explicitly independent of this sample."""

        return self is HarmonicProvenance.INDEPENDENTLY_SELECTED

    @property
    def requires_response_warning(self) -> bool:
        """Return whether response-versus-zero inference needs a provenance warning."""

        return self is not HarmonicProvenance.INDEPENDENTLY_SELECTED


class Alternative(_StringEnum):
    """Alternative hypothesis for a scalar contrast."""

    TWO_SIDED = "two_sided"
    GREATER = "greater"
    LESS = "less"

    @property
    def scipy_value(self) -> str:
        """Return the spelling used by SciPy statistical tests."""

        return "two-sided" if self is Alternative.TWO_SIDED else self.value


class CorrectionMethod(_StringEnum):
    """Supported multiplicity adjustment methods."""

    HOLM = "holm"
    BH_FDR = "fdr_bh"
    NONE = "none"

    @classmethod
    def coerce(cls, value: "CorrectionMethod | str") -> "CorrectionMethod":
        if isinstance(value, cls):
            return value
        normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "bh": cls.BH_FDR,
            "bh_fdr": cls.BH_FDR,
            "benjamini_hochberg": cls.BH_FDR,
            "benjamini_hochberg_fdr": cls.BH_FDR,
            "fdr": cls.BH_FDR,
            "raw": cls.NONE,
            "unadjusted": cls.NONE,
            "uncorrected": cls.NONE,
        }
        if normalized in aliases:
            return aliases[normalized]
        return super().coerce(normalized)  # type: ignore[return-value]


class FollowupProvenance(_StringEnum):
    """Why a follow-up contrast was included in a run."""

    PLANNED = "planned"
    OMNIBUS_TRIGGERED = "omnibus_triggered"
    EXPLORATORY_MANUAL = "exploratory_manual"


class InferenceRole(_StringEnum):
    """Role of a test in the interpretation hierarchy."""

    PRIMARY = "primary"
    EXPLORATORY = "exploratory"
    SENSITIVITY = "sensitivity"


@dataclass(frozen=True)
class FamilySpec:
    """Definition of one named multiple-comparison family."""

    family_id: str
    family_label: str
    method: CorrectionMethod = CorrectionMethod.HOLM
    alpha: float = 0.05

    def __post_init__(self) -> None:
        family_id = str(self.family_id).strip()
        family_label = str(self.family_label).strip()
        if not family_id:
            raise ValueError("family_id must be non-empty.")
        if not family_label:
            raise ValueError("family_label must be non-empty.")
        try:
            alpha = float(self.alpha)
        except (TypeError, ValueError) as exc:
            raise ValueError("alpha must be a number strictly between 0 and 1.") from exc
        if not 0.0 < alpha < 1.0:
            raise ValueError("alpha must be strictly between 0 and 1.")
        object.__setattr__(self, "family_id", family_id)
        object.__setattr__(self, "family_label", family_label)
        object.__setattr__(self, "method", CorrectionMethod.coerce(self.method))
        object.__setattr__(self, "alpha", alpha)

    def to_dict(self) -> dict[str, object]:
        """Return column-ready family metadata."""

        return {
            "family_id": self.family_id,
            "family_label": self.family_label,
            "adjustment_method": self.method.value,
            "alpha": self.alpha,
        }


@dataclass(frozen=True)
class AnalysisRunSpec:
    """Immutable scientific settings shared by workers and reporting code."""

    profile: AnalysisProfile
    harmonic_provenance: HarmonicProvenance
    alpha: float = 0.05
    response_alternative: Alternative = Alternative.TWO_SIDED
    families: tuple[FamilySpec, ...] = field(default_factory=tuple)
    followup_provenance: FollowupProvenance | None = None

    def __post_init__(self) -> None:
        try:
            alpha = float(self.alpha)
        except (TypeError, ValueError) as exc:
            raise ValueError("alpha must be a number strictly between 0 and 1.") from exc
        if not 0.0 < alpha < 1.0:
            raise ValueError("alpha must be strictly between 0 and 1.")
        profile = AnalysisProfile.coerce(self.profile)
        provenance = HarmonicProvenance.coerce(self.harmonic_provenance)
        alternative = Alternative.coerce(self.response_alternative)
        followup = (
            None
            if self.followup_provenance is None
            else FollowupProvenance.coerce(self.followup_provenance)
        )
        families = tuple(self.families)
        if not all(isinstance(spec, FamilySpec) for spec in families):
            raise TypeError("families must contain FamilySpec instances.")
        normalized_ids = [spec.family_id.casefold() for spec in families]
        if len(normalized_ids) != len(set(normalized_ids)):
            raise ValueError("families must have unique family_id values.")
        object.__setattr__(self, "profile", profile)
        object.__setattr__(self, "harmonic_provenance", provenance)
        object.__setattr__(self, "alpha", alpha)
        object.__setattr__(self, "response_alternative", alternative)
        object.__setattr__(self, "families", families)
        object.__setattr__(self, "followup_provenance", followup)

    @property
    def response_is_confirmatory(self) -> bool:
        """Return whether response detection is confirmatory under both contracts."""

        return (
            self.profile is AnalysisProfile.CONFIRMATORY
            and self.harmonic_provenance is HarmonicProvenance.INDEPENDENTLY_SELECTED
        )

    @property
    def response_inference_status(self) -> str:
        """Return a stable interpretation label for response-versus-zero tests."""

        if self.harmonic_provenance is HarmonicProvenance.SAME_SAMPLE_ADAPTIVE:
            return "exploratory_post_selection"
        if self.response_is_confirmatory:
            return "confirmatory"
        if self.profile is AnalysisProfile.CONFIRMATORY:
            return "provenance_unverified"
        return "exploratory"

    @property
    def family_map(self) -> dict[str, FamilySpec]:
        """Return a new mapping keyed by stable family ID."""

        return {spec.family_id: spec for spec in self.families}

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe run metadata."""

        return {
            "profile": self.profile.value,
            "harmonic_provenance": self.harmonic_provenance.value,
            "alpha": self.alpha,
            "response_alternative": self.response_alternative.value,
            "followup_provenance": (
                None if self.followup_provenance is None else self.followup_provenance.value
            ),
            "family_ids": [spec.family_id for spec in self.families],
            "response_is_confirmatory": self.response_is_confirmatory,
            "response_inference_status": self.response_inference_status,
        }


@dataclass(frozen=True)
class TestMetadata:
    """Serializable inventory record for one statistical test or contrast."""

    __test__: ClassVar[bool] = False

    test_id: str
    test_label: str
    method: str
    estimand: str
    role: InferenceRole
    scope: str
    family_id: str | None = None
    alternative: Alternative | None = None
    followup_provenance: FollowupProvenance | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for field_name in ("test_id", "test_label", "method", "estimand", "scope"):
            normalized = str(getattr(self, field_name)).strip()
            if not normalized:
                raise ValueError(f"{field_name} must be non-empty.")
            object.__setattr__(self, field_name, normalized)
        object.__setattr__(self, "role", InferenceRole.coerce(self.role))
        object.__setattr__(
            self,
            "alternative",
            None if self.alternative is None else Alternative.coerce(self.alternative),
        )
        object.__setattr__(
            self,
            "followup_provenance",
            (
                None
                if self.followup_provenance is None
                else FollowupProvenance.coerce(self.followup_provenance)
            ),
        )
        object.__setattr__(
            self,
            "family_id",
            None if self.family_id is None else str(self.family_id).strip() or None,
        )
        object.__setattr__(self, "notes", tuple(str(note) for note in self.notes))

    def to_dict(self) -> dict[str, object]:
        """Return one row for a test-inventory table."""

        return {
            "test_id": self.test_id,
            "test_label": self.test_label,
            "method": self.method,
            "estimand": self.estimand,
            "role": self.role.value,
            "scope": self.scope,
            "family_id": self.family_id,
            "alternative": None if self.alternative is None else self.alternative.value,
            "followup_provenance": (
                None if self.followup_provenance is None else self.followup_provenance.value
            ),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class AnalysisResultMetadata:
    """Run and test metadata that can be exported without DataFrame attributes."""

    run_spec: AnalysisRunSpec
    tests: tuple[TestMetadata, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.run_spec, AnalysisRunSpec):
            raise TypeError("run_spec must be an AnalysisRunSpec.")
        tests = tuple(self.tests)
        if not all(isinstance(test, TestMetadata) for test in tests):
            raise TypeError("tests must contain TestMetadata instances.")
        test_ids = [test.test_id.casefold() for test in tests]
        if len(test_ids) != len(set(test_ids)):
            raise ValueError("tests must have unique test_id values.")
        object.__setattr__(self, "tests", tests)
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe nested representation."""

        return {
            "run": self.run_spec.to_dict(),
            "families": [spec.to_dict() for spec in self.run_spec.families],
            "tests": [test.to_dict() for test in self.tests],
            "warnings": list(self.warnings),
        }

    def to_frames(self) -> dict[str, pd.DataFrame]:
        """Return explicit export frames for run, family, test, and warning metadata."""

        run_row = self.run_spec.to_dict()
        run_row["family_ids"] = "; ".join(str(item) for item in run_row["family_ids"])
        run_frame = pd.DataFrame([run_row])
        family_frame = pd.DataFrame(
            [spec.to_dict() for spec in self.run_spec.families],
            columns=["family_id", "family_label", "adjustment_method", "alpha"],
        )
        test_rows = [test.to_dict() for test in self.tests]
        for row in test_rows:
            row["notes"] = "; ".join(str(note) for note in row["notes"])
        test_frame = pd.DataFrame(
            test_rows,
            columns=[
                "test_id",
                "test_label",
                "method",
                "estimand",
                "role",
                "scope",
                "family_id",
                "alternative",
                "followup_provenance",
                "notes",
            ],
        )
        warning_frame = pd.DataFrame(
            [{"warning": warning} for warning in self.warnings],
            columns=["warning"],
        )
        return {
            "Run Metadata": run_frame,
            "Correction Families": family_frame,
            "Test Inventory": test_frame,
            "Warnings": warning_frame,
        }


def test_inventory_frame(records: Iterable[TestMetadata]) -> pd.DataFrame:
    """Build an explicit inventory frame from test metadata records."""

    result = AnalysisResultMetadata(
        run_spec=AnalysisRunSpec(
            profile=AnalysisProfile.PUBLISHED_STYLE_EXPLORATORY,
            harmonic_provenance=HarmonicProvenance.UNKNOWN,
        ),
        tests=tuple(records),
    )
    return result.to_frames()["Test Inventory"]


__all__ = [
    "Alternative",
    "AnalysisProfile",
    "AnalysisResultMetadata",
    "AnalysisRunSpec",
    "CorrectionMethod",
    "FamilySpec",
    "FollowupProvenance",
    "HarmonicProvenance",
    "InferenceRole",
    "TestMetadata",
    "test_inventory_frame",
]
