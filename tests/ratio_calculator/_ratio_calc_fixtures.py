from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd


def _sheet_frame(
    electrodes: Sequence[str],
    freqs: Sequence[str],
    values: Sequence[Sequence[float | int | None]],
) -> pd.DataFrame:
    data: dict[str, list[float | int | None]] = {"Electrode": list(electrodes)}
    for idx, freq in enumerate(freqs):
        data[freq] = [row[idx] for row in values]
    return pd.DataFrame(data)


def write_ratio_workbook(
    path: Path,
    electrodes: Iterable[str],
    freqs: Iterable[str],
    z_values: Sequence[Sequence[float | int | None]],
    snr_values: Sequence[Sequence[float | int | None]],
    bca_values: Sequence[Sequence[float | int | None]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    electrodes_list = list(electrodes)
    freqs_list = list(freqs)
    with pd.ExcelWriter(path) as writer:
        _sheet_frame(electrodes_list, freqs_list, z_values).to_excel(
            writer,
            sheet_name="Z Score",
            index=False,
        )
        _sheet_frame(electrodes_list, freqs_list, snr_values).to_excel(
            writer,
            sheet_name="SNR",
            index=False,
        )
        _sheet_frame(electrodes_list, freqs_list, bca_values).to_excel(
            writer,
            sheet_name="BCA (uV)",
            index=False,
        )
