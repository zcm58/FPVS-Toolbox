"""Characterize cell decoding and the distinct workbook selection contracts."""

from __future__ import annotations

from io import BytesIO
from xml.etree import ElementTree
import zipfile

import pandas as pd
import pytest

from Main_App.io import spectral_workbook, xlsx_selected_reader, xlsx_xml
from Tools.Plot_Generator import full_snr_reader


def _element(body: str):
    return ElementTree.fromstring(
        f'<root xmlns="{xlsx_xml._SPREADSHEET_NS}">{body}</root>'
    )[0]


@pytest.mark.parametrize(
    "body,strings,text,number",
    [
        ('<c><v>1.2345678901234567</v></c>', [], '1.2345678901234567', 1.2345678901234567),
        ('<c><v>-0.0</v></c>', [], '-0.0', -0.0),
        ('<c t="s"><v>0</v></c>', ['PO8'], 'PO8', 'PO8'),
        ('<c t="s"><v>8</v></c>', [], '8', 8.0),
        ('<c t="s"><v>invalid</v></c>', [], 'invalid', 'invalid'),
        ('<c t="inlineStr"><is><r><t>P</t></r><r><t>O8</t></r></is></c>', [], 'PO8', 'PO8'),
        ('<c t="b"><v>1</v></c>', [], 'TRUE', 'TRUE'),
        ('<c t="b"><v>0</v></c>', [], 'FALSE', 'FALSE'),
        ('<c t="e"><v>#N/A</v></c>', [], '#N/A', '#N/A'),
        ('<c><f>1+1</f><v>2</v></c>', [], '2', 2.0),
        ('<c><v/></c>', [], None, None),
        ('<c/>', [], None, None),
    ],
)
def test_cell_decoding_preserves_text_and_exact_float(body, strings, text, number):
    cell = _element(body)
    assert xlsx_xml._cell_text(cell, strings) == text
    actual = xlsx_xml._cell_number(cell, strings)
    if isinstance(number, float):
        assert actual.hex() == number.hex()
    else:
        assert actual == number


def test_sparse_row_preserves_gaps_and_last_duplicate_cell():
    row = _element(
        '<row><c r="AA1"><v>first</v></c><c r="C1"><v>third</v></c>'
        '<c r="AA1"><v>last</v></c></row>'
    )
    values = xlsx_xml._row_values_by_column(row, [])
    assert len(values) == 27
    assert values[2] == 'third'
    assert values[26] == 'last'
    assert values[:2] == [None, None]
    assert xlsx_xml._cell_column_index(_element('<c/>'), 7) == 7


def test_rich_shared_strings_missing_member_and_invalid_xml():
    stream = BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        assert xlsx_xml._load_shared_strings(archive) == []
        archive.writestr('xl/sharedStrings.xml', (
            f'<sst xmlns="{xlsx_xml._SPREADSHEET_NS}">'
            '<si><r><t>PO</t></r><r><t>8</t></r></si><si><t/></si></sst>'
        ))
        assert xlsx_xml._load_shared_strings(archive) == ['PO8', '']
    with zipfile.ZipFile(BytesIO(), 'w') as archive:
        archive.writestr('xl/sharedStrings.xml', '<broken')
        with pytest.raises(ElementTree.ParseError):
            xlsx_xml._load_shared_strings(archive)


def test_readers_use_one_decoder_and_legacy_module_is_same_object(monkeypatch):
    assert full_snr_reader is spectral_workbook
    assert full_snr_reader._read_full_snr_sheet_read_only is spectral_workbook.read_full_snr_sheet
    for name in ('_cell_text', '_cell_number', '_row_values_by_column', '_load_shared_strings'):
        assert getattr(spectral_workbook, name) is getattr(xlsx_xml, name)
        assert getattr(xlsx_selected_reader, name) is getattr(xlsx_xml, name)
    marker = object()
    monkeypatch.setattr(full_snr_reader, '_load_shared_strings', marker)
    assert spectral_workbook._load_shared_strings is marker


def test_exact_and_window_readers_preserve_their_order_and_filter_contracts(tmp_path):
    workbook = tmp_path / 'spectra.xlsx'
    source = pd.DataFrame({
        'Electrode': ['PO8', 'O1'],
        '2.0000_Hz': [1.23456789012345, -0.125],
        '1.0000_Hz': [3.5, 8.25],
    })
    source.to_excel(workbook, sheet_name='FullSNR', index=False)
    window, freqs, columns = spectral_workbook.read_full_snr_sheet(
        workbook, x_min=1, x_max=2, included_electrodes_upper={'PO8'},
    )
    assert freqs == [1.0, 2.0]
    assert columns == ['1.0000_Hz', '2.0000_Hz']
    exact = xlsx_selected_reader.read_xlsx_sheet_selected_columns(
        workbook, sheet_name='FullSNR',
        required_columns=['2.0000_Hz', 'Electrode', '1.0000_Hz', '2.0000_Hz'],
        included_electrodes_upper={'PO8'},
    )
    assert list(exact.columns) == ['2.0000_Hz', 'Electrode', '1.0000_Hz']
    pd.testing.assert_frame_equal(window, exact.loc[:, ['Electrode', *columns]], check_exact=True)
    with pytest.raises(xlsx_selected_reader.MissingXlsxColumnsError) as failure:
        xlsx_selected_reader.read_xlsx_sheet_selected_columns(
            workbook, sheet_name='FullSNR', required_columns=['7.0000_Hz'],
        )
    assert failure.value.missing_columns == ['7.0000_Hz']


def test_session_reuses_metadata_and_closes_archive_on_failure(tmp_path, monkeypatch):
    workbook = tmp_path / 'spectra.xlsx'
    pd.DataFrame({'Electrode': ['O1'], '1.0000_Hz': [1.25]}).to_excel(
        workbook, sheet_name='FullSNR', index=False,
    )
    calls = []
    load = spectral_workbook._load_shared_strings

    def counted(archive):
        calls.append(archive)
        return load(archive)

    monkeypatch.setattr(spectral_workbook, '_load_shared_strings', counted)
    session = spectral_workbook.XlsxWorkbookReadSession(workbook.read_bytes())
    with pytest.raises(ValueError, match='missing'):
        with session:
            archive = session.archive
            stream = session._stream
            assert session.shared_strings is session.shared_strings
            assert session.worksheet_member('FullSNR') == session.worksheet_member('FullSNR')
            session.worksheet_member('missing')
    assert len(calls) == 1
    assert archive.fp is None
    assert stream.closed
    assert session._archive is None
    assert session._stream is None


def test_duplicate_sheet_resolution_retains_each_readers_existing_policy():
    with zipfile.ZipFile(BytesIO(), 'w') as archive:
        archive.writestr('xl/workbook.xml', (
            f'<workbook xmlns="{xlsx_xml._SPREADSHEET_NS}" '
            f'xmlns:r="{xlsx_xml._OFFICE_REL_NS}"><sheets>'
            '<sheet name="same" r:id="r1"/><sheet name="same" r:id="r2"/>'
            '</sheets></workbook>'
        ))
        archive.writestr('xl/_rels/workbook.xml.rels', (
            f'<Relationships xmlns="{xlsx_xml._PACKAGE_REL_NS}">'
            '<Relationship Id="r1" Target="worksheets/first.xml"/>'
            '<Relationship Id="r2" Target="/xl/worksheets/last.xml"/>'
            '</Relationships>'
        ))
        assert xlsx_selected_reader._worksheet_member(archive, 'same') == 'xl/worksheets/first.xml'
        assert spectral_workbook._worksheet_members(archive)['same'] == 'xl/worksheets/last.xml'
