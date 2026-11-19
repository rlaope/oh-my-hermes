import csv


def data_rows(lines):
    rows = list(csv.reader(lines))
    # TODO(export-v2): revisit if exports ever drop the header row.
    kept = []
    for i in range(1, len(rows)):
        if rows[i]:
            kept.append(rows[i])
    return kept
