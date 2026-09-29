# Retained Receiver Receipt

`retained_426_marker_receipt.json` is a portable extraction of the retained
test-signal receiver receipt from diagnostic bundle `2026-09-28-2bce2ff1`.
The source receipt, BDF, and CSV hashes are recorded in the fixture. All nine
files in that bundle matched its retained SHA256 manifest when checked on
2026-09-29. No raw binary or CSV is copied here.

The 426 code/sample pairs are copied from `receiver-results.json`, not generated
from a synthetic schedule. The fixture omits machine paths, header dates/times,
sender wall/monotonic clocks, and participant/session metadata. Additional
format fields come from the matched BDF's header. In particular, `?V` is the
literal recorded EEG dimension (bytes `3F 56`), not a display decoding artifact.

This fixture supports decoder regression only. The source used Recorder's
test-signal input. Marker agreement does not qualify EEG channel wiring,
reference, amplitude scaling, telemetry loss semantics, absolute clock origin,
or physical display-to-EEG timing. The file is classic `24BIT` BDF, not BDF+.
Every nonzero Status sample is one marker in this observed configuration;
four adjacent equal-code pairs must not collapse into a single event.
