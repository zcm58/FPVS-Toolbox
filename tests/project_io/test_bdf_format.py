from contextlib import contextmanager
from decimal import Decimal, localcontext
import hashlib
import os
from pathlib import Path

import mne
import numpy as np
import pytest

from Main_App.io.bdf_format import BdfFormatError, inspect_bdf_format
from tests.bdf_factory import write_bdf


def test_classic_native_samples_and_signed_scaling_are_preserved(tmp_path):
    values = [0, 1, -1, 8388607, -8388608] + [0] * 245
    path = write_bdf(tmp_path / "classic.bdf", variant="BDF", record_onsets=("0",),
                     signal_values={"Fz": [values]})
    result = inspect_bdf_format(path, digital_channels=("Fz", "Status"))
    assert result.header.variant == "BDF"
    assert result.header.signals[0].physical_dimension == "uV"
    assert result.header.signals[0].identity_scaling
    assert result.digital_signals[0] == ("Fz", tuple(values))
    assert result.file_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result.annotations == ()
    assert not result.processing_blockers
    with mne.io.read_raw_bdf(path, preload=False, verbose=False) as raw:
        assert raw.info["sfreq"] == 250
        np.testing.assert_allclose(raw.get_data(picks=["Fz"])[0], np.array(values) * 1e-6)


def test_bdf_plus_preserves_fractional_origin_tal_order_and_notes(tmp_path):
    path = write_bdf(tmp_path / "continuous.bdf", record_onsets=("0.125", "1.125"),
                     annotations=((b"+0.133\x14" b"7\x14note\x14\x00",),
                                  (b"+1.225\x15" b"0.04\x14artifact\x14\x00",)))
    result = inspect_bdf_format(path)
    assert result.header.variant == "BDF+C"
    assert result.record_onsets == (Decimal("0.125"), Decimal("1.125"))
    assert result.first_sample_onset == Decimal("0.125")
    assert [a.text for a in result.annotations] == ["", "7", "note", "", "artifact"]
    assert [a.source_order for a in result.annotations] == list(range(5))
    assert len({a.source_id for a in result.annotations}) == 5
    assert [a.is_timekeeping for a in result.annotations] == [True, False, False, True, False]
    assert result.annotations[-1].duration_seconds == Decimal("0.04")
    assert not result.processing_blockers
    with mne.io.read_raw_bdf(path, preload=False, verbose=False) as raw:
        assert raw.n_times == 500
        assert list(raw.annotations.description) == ["7", "note", "artifact"]


@pytest.mark.parametrize("variant", ["BDF+C", "BDF+D"])
def test_discontinuity_is_preserved_before_reader_flattening(tmp_path, variant):
    path = write_bdf(tmp_path / "gap.bdf", variant=variant, record_onsets=("0", "2"))
    result = inspect_bdf_format(path)
    assert result.record_onsets == (Decimal(0), Decimal(2))
    assert result.processing_blockers


def test_bdf_d_is_inspection_only_even_when_records_happen_to_be_contiguous(tmp_path):
    path = write_bdf(tmp_path / "declared_discontinuous.bdf", variant="BDF+D")
    assert "BDF+D" in inspect_bdf_format(path).processing_blockers[0]


def test_annotation_only_markers_do_not_require_stim(tmp_path):
    path = write_bdf(tmp_path / "annotation_only.bdf", status=False,
                     annotations=((b"+0.004\x14" b"1\x14\x00",),))
    result = inspect_bdf_format(path)
    assert [signal.label for signal in result.header.signals] == ["Fz", "BDF Annotations"]
    assert result.annotations[1].text == "1"


@pytest.mark.parametrize("onsets", [("0", "0.5"), ("1", "2")])
def test_reversed_overlap_or_invalid_first_origin_rejected(tmp_path, onsets):
    path = write_bdf(tmp_path / "bad_timing.bdf", record_onsets=onsets)
    with pytest.raises(BdfFormatError):
        inspect_bdf_format(path)


@pytest.mark.parametrize("tal", [b"+0.1\x14unterminated", b"0.1\x14bad\x14\x00",
                                  b"+0.1\x15-1\x14bad\x14\x00", b"+0.1\x14\xff\x14\x00",
                                  b"\x00+0.1\x14bad\x14\x00"])
def test_malformed_annotations_rejected(tmp_path, tal):
    path = write_bdf(tmp_path / "bad_tal.bdf", annotations=((tal,),))
    with pytest.raises(BdfFormatError):
        inspect_bdf_format(path)


@pytest.mark.parametrize("offset,value", [(0, b"0       "), (192, b"EDF+C"),
    (236, b"-1      "), (244, b"0       "), (184, b"256     ")])
def test_invalid_header_is_not_silently_repaired(tmp_path, offset, value):
    path = write_bdf(tmp_path / "bad_header.bdf")
    data = bytearray(path.read_bytes())
    data[offset:offset + len(value)] = value
    path.write_bytes(data)
    with pytest.raises(BdfFormatError):
        inspect_bdf_format(path)


def test_truncated_samples_and_duplicate_labels_fail(tmp_path):
    path = write_bdf(tmp_path / "truncated.bdf")
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(BdfFormatError, match="file size"):
        inspect_bdf_format(path)
    write_bdf(path, eeg_names=("Fz", "fz"))
    with pytest.raises(BdfFormatError, match="Duplicate"):
        inspect_bdf_format(path)


def test_unknown_physical_unit_is_preserved_not_interpreted(tmp_path):
    path = write_bdf(tmp_path / "unit.bdf", unit="?V",
                     signal_values={"Fz": [[4000] * 250] * 2})
    result = inspect_bdf_format(path)
    assert result.header.signals[0].physical_dimension == "?V"
    assert result.digital_signals == ()
    with mne.io.read_raw_bdf(path, preload=False, verbose=False) as raw:
        # The malformed vendor unit is not converted to volts by MNE.
        np.testing.assert_allclose(raw.get_data(picks=["Fz"]), 4000)


def test_requested_channels_must_be_exact_and_unique(tmp_path):
    path = write_bdf(tmp_path / "missing.bdf")
    for names in (("stim",), ("Status", "Status")):
        with pytest.raises(BdfFormatError, match="missing or duplicated"):
            inspect_bdf_format(path, digital_channels=names)


def test_exact_high_precision_tal_continuity_does_not_depend_on_decimal_context(tmp_path):
    onsets = ("0.123456789012345678901234567890", "1.123456789012345678901234567890")
    path = write_bdf(tmp_path / "exact_timing.bdf", record_onsets=onsets)
    with localcontext() as context:
        context.prec = 6
        result = inspect_bdf_format(path)
    assert result.record_onsets == tuple(Decimal(onset) for onset in onsets)
    assert not result.processing_blockers


def test_sub_decimal_context_precision_gap_is_still_detected(tmp_path):
    onsets = ("0.123456789012345678901234567890", "1.123456789012345678901234567891")
    path = write_bdf(tmp_path / "tiny_gap.bdf", record_onsets=onsets)
    result = inspect_bdf_format(path)
    assert result.record_onsets == tuple(Decimal(onset) for onset in onsets)
    assert result.processing_blockers == ("BDF+C record timestamps are not contiguous.",)


@pytest.mark.parametrize("duration", ["1_0", "0x1", "NaN", "Infinity", "1,0", "1 0", "+"])
def test_header_numbers_reject_non_format_decimal_syntax(tmp_path, duration):
    path = write_bdf(tmp_path / "invalid_decimal.bdf", record_duration=duration)
    with pytest.raises(BdfFormatError, match="Invalid numeric BDF field: record duration"):
        inspect_bdf_format(path)


def test_header_supports_scientific_decimal_notation_without_rounding(tmp_path):
    path = write_bdf(tmp_path / "scientific_decimal.bdf", record_duration="4E-3",
                     samples_per_record=1, record_onsets=("0", "0.004"))
    result = inspect_bdf_format(path)
    assert result.header.record_duration == Decimal("0.004")
    assert not result.processing_blockers


def _matching_replacement_files(tmp_path):
    path = write_bdf(tmp_path / "original.bdf", record_onsets=("0",))
    replacement = write_bdf(tmp_path / "replacement.bdf", record_onsets=("0",),
                            signal_values={"Fz": [[1] * 250]})
    original_stat = path.stat()
    os.utime(replacement, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert path.stat().st_size == replacement.stat().st_size
    assert path.stat().st_mtime_ns == replacement.stat().st_mtime_ns
    return path, replacement


def test_replacement_between_path_stat_and_open_is_rejected_and_handle_closed(tmp_path, monkeypatch):
    path, replacement = _matching_replacement_files(tmp_path)
    original_open = Path.open
    opened = []

    def replacement_open(current, *args, **kwargs):
        if current == path:
            stream = original_open(replacement, *args, **kwargs)
            opened.append(stream)
            return stream
        return original_open(current, *args, **kwargs)

    monkeypatch.setattr(Path, "open", replacement_open)
    with pytest.raises(BdfFormatError, match="replaced before inspection"):
        inspect_bdf_format(path)
    assert len(opened) == 1 and opened[0].closed


def test_path_replacement_after_read_is_rejected_even_when_size_and_mtime_match(tmp_path, monkeypatch):
    path, replacement = _matching_replacement_files(tmp_path)
    original_open = Path.open
    opened = []

    @contextmanager
    def replacing_open(current, *args, **kwargs):
        with original_open(current, *args, **kwargs) as stream:
            opened.append(stream)
            yield stream
        if current == path:
            # The handle has closed, so this also exercises the race on Windows.
            os.replace(replacement, path)

    monkeypatch.setattr(Path, "open", replacing_open)
    with pytest.raises(BdfFormatError, match="changed during inspection"):
        inspect_bdf_format(path)
    assert len(opened) == 1 and opened[0].closed


def test_optional_channels_match_casefold_preserve_source_order_and_skip_absent(tmp_path):
    path = write_bdf(tmp_path / "optional.bdf", record_onsets=("0",),
                     signal_values={"Fz": [[17] * 250], "Status": [[55] * 250]})
    before = path.read_bytes()
    result = inspect_bdf_format(path, optional_digital_channels=("STATUS", "fz", "CNT", "BDF Annotations"))
    assert result.digital_signals == (("Fz", (17,) * 250), ("Status", (55,) * 250))
    assert inspect_bdf_format(path, optional_digital_channels=("CNT",)).digital_signals == ()
    assert path.read_bytes() == before


@pytest.mark.parametrize("requested", [("Status", "status"), ("CNT", "cnt"), ("Status", "Status")])
def test_optional_duplicate_requests_fail_even_when_channel_absent(tmp_path, requested):
    path = write_bdf(tmp_path / "duplicate_optional.bdf")
    with pytest.raises(BdfFormatError, match="Optional digital channels are duplicated"):
        inspect_bdf_format(path, optional_digital_channels=requested)


def test_required_and_optional_same_channel_is_materialized_once(tmp_path):
    path = write_bdf(tmp_path / "required_optional.bdf", record_onsets=("0",),
                     signal_values={"Status": [[55] * 250]})
    result = inspect_bdf_format(path, digital_channels=("Status",), optional_digital_channels=("status",))
    assert result.digital_signals == (("Status", (55,) * 250),)


def _replace_first_annotation_payload(path, payload):
    data = bytearray(path.read_bytes())
    channel_count = int(data[252:256])
    samples_offset = 256 + 216 * channel_count
    samples = [int(data[samples_offset + index * 8:samples_offset + (index + 1) * 8])
               for index in range(channel_count)]
    annotation_offset = int(data[184:192]) + sum(samples[:-1]) * 3
    annotation_size = samples[-1] * 3
    assert len(payload) <= annotation_size
    data[annotation_offset:annotation_offset + annotation_size] = payload.ljust(annotation_size, b"\x00")
    path.write_bytes(data)


@pytest.mark.parametrize("payload", [b"", b"+0\x14not_timekeeping\x14\x00", b"+0\x150\x14\x14\x00"])
def test_missing_or_duration_bearing_record_timekeeping_is_rejected(tmp_path, payload):
    path = write_bdf(tmp_path / "missing_timekeeping.bdf", record_onsets=("0",))
    _replace_first_annotation_payload(path, payload)
    with pytest.raises(BdfFormatError, match="Missing BDF\\+ record timekeeping annotation"):
        inspect_bdf_format(path)


def test_parser_failure_closes_source_handle(tmp_path, monkeypatch):
    path = write_bdf(tmp_path / "invalid_timing.bdf", record_onsets=("0",))
    _replace_first_annotation_payload(path, b"+0\x14not_timekeeping\x14\x00")
    original_open = Path.open
    opened = []

    def tracked_open(current, *args, **kwargs):
        stream = original_open(current, *args, **kwargs)
        opened.append(stream)
        return stream

    monkeypatch.setattr(Path, "open", tracked_open)
    with pytest.raises(BdfFormatError):
        inspect_bdf_format(path)
    assert len(opened) == 1 and opened[0].closed
