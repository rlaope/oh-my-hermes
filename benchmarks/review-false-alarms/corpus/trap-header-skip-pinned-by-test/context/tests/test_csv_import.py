import unittest

from app.csv_import import data_rows


class DataRowsTests(unittest.TestCase):
    def test_header_row_is_not_data(self):
        lines = ["sku,qty", "a-1,3", "", "b-2,5"]
        self.assertEqual(data_rows(lines), [["a-1", "3"], ["b-2", "5"]])

    def test_header_only_export_has_no_rows(self):
        self.assertEqual(data_rows(["sku,qty"]), [])
