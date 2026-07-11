"""Generic CSV/XLSX template builders — entity-agnostic. Entity modules
supply (labels, example_row); this module only turns that into file
bytes, so a future Products/Services/etc. import reuses these two
functions unchanged — only the labels/example values differ.
"""

import csv
import io

from openpyxl import Workbook


def build_csv_template(labels: list[str], example_row: list[str]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(labels)
    writer.writerow(example_row)
    # utf-8-sig so Excel on Windows opens accented headers correctly
    # instead of mangling them (the same BOM this app's CSV parser already
    # accepts on the way in — see app/imports/parsers.py).
    return buffer.getvalue().encode("utf-8-sig")


def build_xlsx_template(labels: list[str], example_row: list[str]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(labels)
    sheet.append(example_row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
