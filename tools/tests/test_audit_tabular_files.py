"""Regression checks for transfer damage that can otherwise evade review."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

import openpyxl

SOURCE = Path(__file__).resolve().parents[1] / "audit_tabular_files.py"
SPEC = importlib.util.spec_from_file_location("audit_tabular_files", SOURCE)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class TabularAuditTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def csv_file(self, content):
        path = self.root / "sample.csv"
        path.write_bytes(content)
        return path

    def test_empty_transfer_is_rejected(self):
        result = AUDIT.audit_file(self.csv_file(b""), self.root)
        self.assertEqual(result["status"], "fail")

    def test_truncated_quoted_record_is_rejected(self):
        result = AUDIT.audit_file(self.csv_file(b'name,value\n"unfinished'), self.root)
        self.assertEqual(result["status"], "fail")

    def test_partial_unquoted_record_is_rejected(self):
        result = AUDIT.audit_file(self.csv_file(b'name,value\ncomplete,1\npartial'), self.root)
        self.assertEqual(result["status"], "fail")

    def test_quoted_newlines_commas_and_trailing_blank_line_are_valid(self):
        result = AUDIT.audit_file(self.csv_file(b'name,value\n"one,two","a\nb"\n\n'), self.root)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["data_rows"], 1)
        self.assertEqual(result["blank_records"], 1)

    def test_header_only_table_is_valid(self):
        result = AUDIT.audit_file(self.csv_file(b"name,value\n"), self.root)
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["header_only"])

    def test_baseline_catches_truncation_at_complete_record(self):
        path = self.csv_file(b"name,value\nfirst,1\nsecond,2\n")
        original = AUDIT.audit_file(path, self.root)
        path.write_bytes(b"name,value\nfirst,1\n")
        truncated = AUDIT.audit_file(path, self.root)
        self.assertEqual(truncated["status"], "pass")
        self.assertEqual(AUDIT.compare_baseline([truncated], {"files": [original]}),
                         [{"path": "sample.csv", "change": "content_changed"}])

    def test_complete_and_truncated_workbook(self):
        path = self.root / "sample.xlsx"
        book = openpyxl.Workbook()
        book.active.append(["name", "value"])
        book.active.append(["example", 1])
        book.save(path)
        book.close()
        complete = AUDIT.audit_file(path, self.root)
        self.assertEqual(complete["status"], "pass")
        self.assertEqual(complete["sheets"][0]["rows_including_header"], 2)
        path.write_bytes(path.read_bytes()[:-100])
        self.assertEqual(AUDIT.audit_file(path, self.root)["status"], "fail")

    def test_git_recovery_backups_are_not_current_data(self):
        expected = self.csv_file(b"column\nvalue\n")
        backup = self.root / ".git" / "recovery-backups" / "old.csv"
        backup.parent.mkdir(parents=True)
        backup.write_bytes(b"broken")
        self.assertEqual(AUDIT.inventory(self.root), [expected])

    def test_inaccurate_dimensions_do_not_hide_rows(self):
        original = self.root / "original.xlsx"
        book = openpyxl.Workbook()
        book.active.append(["name", "value"])
        book.active.append(["example", 1])
        book.save(original)
        book.close()
        rewritten = self.root / "bad-dimension.xlsx"
        with zipfile.ZipFile(original) as source, zipfile.ZipFile(rewritten, "w") as target:
            for member in source.infolist():
                content = source.read(member.filename)
                if member.filename == "xl/worksheets/sheet1.xml":
                    content = content.replace(b'<dimension ref="A1:B2"', b'<dimension ref="A1"')
                target.writestr(member, content)
        result = AUDIT.audit_file(rewritten, self.root)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["sheets"][0]["rows_including_header"], 2)


if __name__ == "__main__":
    unittest.main()
