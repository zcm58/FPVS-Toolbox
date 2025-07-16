import importlib.util
import pytest

if importlib.util.find_spec("pandas") is None:
    pytest.skip("pandas not available", allow_module_level=True)
else:
    import pandas as pd

spec = importlib.util.spec_from_file_location(
    'stats_analysis',
    str(__import__('pathlib').Path(__file__).resolve().parent.parent / 'src' / 'Tools' / 'Stats' / 'stats_analysis.py')
)
stats_analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stats_analysis)


def test_aggregate_bca_sum_four_decimals(tmp_path):
    # Create dataframe with 4-decimal freq columns
    cols = ['6.0000_Hz', '7.2000_Hz', '12.0000_Hz']
    idx = ['F3', 'F4', 'Fz']
    data = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
    df = pd.DataFrame(data, index=idx, columns=cols)
    df.insert(0, 'Electrode', df.index)
    file_path = tmp_path / 'data.xlsx'
    with pd.ExcelWriter(file_path) as writer:
        df.to_excel(writer, sheet_name='BCA (uV)', index=False)
    stats_analysis.set_rois({'TestROI': idx})
    logs = []
    result = stats_analysis.aggregate_bca_sum(str(file_path), 'TestROI', base_freq='6.0', log_func=logs.append)
    assert not any('No matching BCA freq columns' in m for m in logs)
    # Only 7.2 Hz should be included (not multiple of base freq)
    assert result == df['7.2000_Hz'].mean()
