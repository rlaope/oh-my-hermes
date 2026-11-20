import csv
from pathlib import Path


class Exporter:
    """Writes rows to a CSV file. Use it as a context manager.

    The file is created on the first row, so an export with no rows leaves no file.
    """

    def __init__(self, path: Path, header: list[str]) -> None:
        self.path = path
        self.header = header
        self._fh = None
        self._writer = None

    def write(self, row: list[str]) -> None:
        if self._fh is None:
            self._fh = self.path.open("w", newline="", encoding="utf-8")
            self._writer = csv.writer(self._fh)
            self._writer.writerow(self.header)
        self._writer.writerow(row)

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "Exporter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
