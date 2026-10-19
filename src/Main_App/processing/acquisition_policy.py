"""Compatibility imports for the upstream acquisition metadata boundary.

New processing code consumes ``io.recording_contract.RecordingContract``;
manufacturer interpretation lives in ``io.acquisition_metadata``.
"""

from Main_App.io.acquisition_metadata import (
    ACQUISITION_POLICY_ATTRIBUTE as ACQUISITION_POLICY_ATTRIBUTE,
    BRAIN_PRODUCTS_PIPELINE_VERSION as BRAIN_PRODUCTS_PIPELINE_VERSION,
    ResolvedAcquisitionPolicy as ResolvedAcquisitionPolicy,
    apply_brain_products_reference as apply_brain_products_reference,
    apply_recorded_reference as apply_recorded_reference,
    attach_acquisition_policy as attach_acquisition_policy,
    brain_products_policy as brain_products_policy,
    event_detection_kwargs as event_detection_kwargs,
    freeze_retained_geometry as freeze_retained_geometry,
    is_brain_products as is_brain_products,
    policy_fingerprint as policy_fingerprint,
    resolve_acquisition_policy as resolve_acquisition_policy,
    validate_brain_products_qc as validate_brain_products_qc,
)
