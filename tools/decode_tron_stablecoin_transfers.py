from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from daos.tron import decode_stablecoin_transfers


def main() -> None:
    parser = argparse.ArgumentParser(description="Decode USDT TRC20 transfer calls from a raw Tron CSV into JSONL.")
    parser.add_argument("--input", default=str(ROOT / "data" / "raw_data" / "2023-01-01.csv"))
    parser.add_argument("--output", default=str(ROOT / "data" / "processed" / "tron_stablecoin_transfers" / "transfers.jsonl"))
    parser.add_argument("--max-rows", type=int, default=100000, help="Rows to scan; use 0 for full file.")
    args = parser.parse_args()

    max_rows = None if args.max_rows == 0 else args.max_rows
    summary = decode_stablecoin_transfers(args.input, args.output, max_rows=max_rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
