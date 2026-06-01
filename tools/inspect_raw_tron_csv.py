from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from daos.tron import inspect_raw_csv, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a raw Tron CSV without loading it into memory.")
    parser.add_argument("--input", default=str(ROOT / "data" / "raw_data" / "2023-01-01.csv"))
    parser.add_argument("--max-rows", type=int, default=100000, help="Rows to scan; use 0 for full file.")
    parser.add_argument("--output", default=str(ROOT / "data" / "processed" / "raw_tron_csv_inspection.json"))
    args = parser.parse_args()

    max_rows = None if args.max_rows == 0 else args.max_rows
    stats = inspect_raw_csv(args.input, max_rows=max_rows)
    payload = asdict(stats)
    write_json(args.output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
