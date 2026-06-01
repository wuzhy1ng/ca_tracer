from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from daos.tron import build_raw_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a manifest for raw Tron CSV files using actual timestamp ranges.")
    parser.add_argument("--input-dir", default=str(ROOT / "data" / "raw_data"))
    parser.add_argument("--output", default=str(ROOT / "data" / "raw_data" / "manifest_2023.json"))
    parser.add_argument("--max-rows-per-file", type=int, default=100000, help="Use 0 to scan full files.")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    files = sorted(path for path in input_dir.rglob("*.csv") if path.is_file())
    max_rows = None if args.max_rows_per_file == 0 else args.max_rows_per_file
    manifest = build_raw_manifest(files, args.output, max_rows_per_file=max_rows)
    print(json.dumps({"output": args.output, "file_count": len(manifest["files"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
