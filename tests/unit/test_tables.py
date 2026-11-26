"""VRT-120: a table built from SLANet's cells and the OCR lines, kept only
when it was built right. No model: its output is given."""

from __future__ import annotations

from idp.extraction.grounding import find_source_block
from idp.parsing.normalize import ParsedBlock, ParsedDocument
from idp.parsing.tables import Line, cell_boxes, to_html

# A header over two columns, then two rows: concept and amount.
STRUCTURE = ["<table>", "<tr>", '<td colspan="2">', "</td>", "</tr>", "<tr>", "<td>", "</td>", "<td>", "</td>", "</tr>", "<tr>", "<td>", "</td>", "<td>", "</td>", "</tr>", "</table>"]
CELLS = [(0, 0, 200, 20), (0, 20, 100, 40), (100, 20, 200, 40), (0, 40, 100, 60), (100, 40, 200, 60)]
LINES = [Line(1, "INGRESOS", (60, 5, 140, 15)), Line(2, "VPRI-65%", (5, 25, 90, 35)), Line(3, "4 418,05", (110, 25, 190, 35)),
         Line(4, "S.RIMAC", (5, 45, 90, 55)), Line(5, "325,40", (110, 45, 190, 55))]


def test_each_cell_gets_its_lines_and_names_them():
    html = to_html(STRUCTURE, CELLS, LINES, line_height=10)
    assert html == ('<table><tr><td colspan="2" r="1">INGRESOS</td></tr><tr><td r="2">VPRI-65%</td><td r="3">4 418,05</td></tr>'
                    '<tr><td r="4">S.RIMAC</td><td r="5">325,40</td></tr></table>')


def test_a_cell_holding_several_rows_drops_the_table():
    merged = [(0, 0, 200, 20), (0, 20, 100, 60), (100, 20, 200, 60), (0, 60, 100, 70), (100, 60, 200, 70)]
    assert to_html(STRUCTURE, merged, LINES, line_height=10) is None


def test_a_single_column_or_lost_lines_drop_it():
    one_column = ["<table>", "<tr>", "<td>", "</td>", "</tr>", "<tr>", "<td>", "</td>", "</tr>", "</table>"]
    assert to_html(one_column, [(0, 0, 200, 30), (0, 30, 200, 60)], LINES[1:3], line_height=10) is None
    assert to_html(STRUCTURE, CELLS[:1] + [(900, 900, 901, 901)] * 4, LINES, line_height=10) is None, "most lines in no cell"


def test_cells_come_in_page_pixels():
    assert cell_boxes([[1, 2, 11, 2, 11, 12, 1, 12]], (100, 200)) == [(101.0, 202.0, 111.0, 212.0)]


def test_a_value_is_grounded_to_its_line_not_to_the_table():
    line = ParsedBlock(region_id=3, text="4 418,05", page=0, bbox=[0.5, 0.1, 0.6, 0.12], confidence=0.99)
    table = ParsedBlock(region_id=7, text="<table><tr><td r=\"3\">4 418,05 TOTAL INGRESOS 6 618,00</td></tr></table>", page=0, bbox=[0, 0, 1, 1], confidence=0.9, block_type="table")
    parsed = ParsedDocument(backend="t", page_count=1, blocks=[table, line])
    assert find_source_block("4 418,05", parsed) is line
    assert find_source_block("4 418,05 TOTAL INGRESOS", parsed) is not table
    assert "<table>" not in parsed.full_text
