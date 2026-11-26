# Data Share Review Offline Residual Scanner (`residual_scan.py`)

Offline Python 3.11+ standard-library companion script for `omh-data-share-review`.
It scans a file about to leave the team (CSV, JSON/JSONL, or plain text) and prints
strictly metadata-only `residual_scan/v1` counts and the SHA-256 digest of the scanned
bytes.

## Safety Boundary

- **Counts only, never matched values**: matched emails, phone numbers, tokens, or IDs
  are never echoed to stdout or stderr.
- **Offline and dependency-free**: uses only the Python 3.11+ standard library; makes no
  network calls and uploads nothing.
- **Free-text sample rule**: zero regex hits alone yields `needs_free_text_sample` until
  a reviewer also samples free-text fields and passes `--free-text-sampled`.

## Usage

```sh
python3 toolkit/scripts/residual_scan.py --input /path/to/export.csv --json
python3 toolkit/scripts/residual_scan.py --input /path/to/export.csv --free-text-sampled --json
```
