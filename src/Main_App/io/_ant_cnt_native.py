"""Read-only subprocess entry point for the ANT-specific libeep extension."""
from importlib.metadata import version
import json
import sys


def main(path: str) -> None:
    try:
        from antio import read_cnt
    except ImportError as exc:
        raise SystemExit("Install antio in the Toolbox Python environment to read ANT CNT recordings.") from exc
    # Use the same backend as mne.io.read_raw_ant. Its source trigger access
    # retains integer samples, native row order and recorder-specific metadata.
    cnt = read_cnt(path)
    make, model, _serial = cnt.get_machine_info(encoding="latin-1")
    json.dump({
        "reader_version": version("antio"), "amp_make": make, "amp_model": model,
        "sampling_rate_hz": cnt.get_sample_frequency(), "sample_count": cnt.get_sample_count(),
        "events": [cnt.get_trigger(i) for i in range(cnt.get_trigger_count())],
    }, sys.stdout)


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except (ValueError, RuntimeError, OSError) as error:
        raise SystemExit(str(error)) from error
