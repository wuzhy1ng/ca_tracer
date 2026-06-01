from __future__ import annotations

import ast
import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Iterable


getcontext().prec = 28

USDT_TRC20_HEX = "41a614f803b6fd780986a42c78ec9c7f77e6ded13c"
TRANSFER_SELECTOR = "a9059cbb"
TRON_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


@dataclass
class RawCsvStats:
    path: str
    rows_seen: int
    first_timestamp: int | None
    first_time: str | None
    last_timestamp: int | None
    last_time: str | None
    min_timestamp: int | None
    min_time: str | None
    max_timestamp: int | None
    max_time: str | None
    transfer_like_rows: int
    usdt_transfer_rows: int


@dataclass
class StablecoinTransfer:
    txid: str
    block_number: int | None
    timestamp: int
    time: str
    time_utc: str
    time_local: str
    token_contract: str
    asset: str
    from_address: str
    to_address: str
    amount_raw: str
    amount: str
    direction_hint: str = "unknown"
    transaction_index: int | None = None


def timestamp_to_iso(timestamp_ms: int | None) -> str | None:
    if timestamp_ms is None:
        return None
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).replace(tzinfo=None).isoformat(sep=" ")


def timestamp_to_local_iso(timestamp_ms: int | None, offset_hours: int = 8) -> str | None:
    if timestamp_ms is None:
        return None
    utc_dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    return (utc_dt + timedelta(hours=offset_hours)).replace(tzinfo=None).isoformat(sep=" ")


def _base58_encode(payload: bytes) -> str:
    value = int.from_bytes(payload, "big")
    encoded = ""
    while value:
        value, rem = divmod(value, 58)
        encoded = TRON_B58_ALPHABET[rem] + encoded
    leading_zeroes = len(payload) - len(payload.lstrip(b"\0"))
    return "1" * leading_zeroes + (encoded or "1")


def tron_hex_to_base58(hex_address: str) -> str:
    import hashlib

    raw = bytes.fromhex(hex_address)
    checksum = hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4]
    return _base58_encode(raw + checksum)


def decode_tron_address_word(word: str) -> str:
    cleaned = word.lower().removeprefix("0x")
    if len(cleaned) != 64:
        raise ValueError(f"ABI address word must be 64 hex chars, got {len(cleaned)}")
    last_42 = cleaned[-42:]
    if last_42.startswith("41"):
        return last_42
    return "41" + cleaned[-40:]


def parse_raw_data(raw_data: str) -> dict | None:
    try:
        parsed = ast.literal_eval(raw_data)
    except (SyntaxError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def iter_raw_rows(csv_path: Path | str) -> Iterable[dict]:
    with Path(csv_path).open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        yield from reader


def _int_or_none(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def decode_transfer_row(row: dict, token_contract: str = USDT_TRC20_HEX, asset: str = "USDT", decimals: int = 6) -> StablecoinTransfer | None:
    raw = parse_raw_data(row.get("raw_data", ""))
    if not raw:
        return None

    contracts = raw.get("contract")
    if not isinstance(contracts, list):
        return None

    for contract in contracts:
        if contract.get("type") != "TriggerSmartContract":
            continue
        value = (((contract.get("parameter") or {}).get("value")) or {})
        contract_address = str(value.get("contract_address", "")).lower()
        data = str(value.get("data", "")).lower()
        owner_address = str(value.get("owner_address", "")).lower()
        if contract_address != token_contract.lower():
            continue
        if not data.startswith(TRANSFER_SELECTOR) or len(data) < 8 + 64 + 64:
            continue

        to_hex = decode_tron_address_word(data[8 : 8 + 64])
        amount_raw = int(data[8 + 64 : 8 + 128], 16)
        timestamp = _int_or_none(row.get("timestamp"))
        if timestamp is None:
            timestamp = _int_or_none(raw.get("timestamp"))
        if timestamp is None:
            continue

        amount = Decimal(amount_raw) / (Decimal(10) ** decimals)
        return StablecoinTransfer(
            txid=str(row.get("transaction_hash") or ""),
            block_number=_int_or_none(row.get("block_number")),
            timestamp=timestamp,
            time=timestamp_to_iso(timestamp) or "",
            time_utc=timestamp_to_iso(timestamp) or "",
            time_local=timestamp_to_local_iso(timestamp) or "",
            token_contract=contract_address,
            asset=asset,
            from_address=tron_hex_to_base58(owner_address),
            to_address=tron_hex_to_base58(to_hex),
            amount_raw=str(amount_raw),
            amount=format(amount.normalize(), "f"),
            transaction_index=_int_or_none(row.get("transaction_index")),
        )
    return None


def inspect_raw_csv(csv_path: Path | str, max_rows: int | None = None) -> RawCsvStats:
    rows_seen = 0
    first_ts = None
    last_ts = None
    min_ts = None
    max_ts = None
    transfer_like = 0
    usdt_transfer = 0

    for row in iter_raw_rows(csv_path):
        rows_seen += 1
        timestamp = _int_or_none(row.get("timestamp"))
        if timestamp is not None:
            first_ts = timestamp if first_ts is None else first_ts
            last_ts = timestamp
            min_ts = timestamp if min_ts is None else min(min_ts, timestamp)
            max_ts = timestamp if max_ts is None else max(max_ts, timestamp)

        raw_data = row.get("raw_data", "")
        if TRANSFER_SELECTOR in raw_data:
            transfer_like += 1
        if USDT_TRC20_HEX in raw_data.lower() and TRANSFER_SELECTOR in raw_data:
            usdt_transfer += 1

        if max_rows is not None and rows_seen >= max_rows:
            break

    return RawCsvStats(
        path=str(csv_path),
        rows_seen=rows_seen,
        first_timestamp=first_ts,
        first_time=timestamp_to_iso(first_ts),
        last_timestamp=last_ts,
        last_time=timestamp_to_iso(last_ts),
        min_timestamp=min_ts,
        min_time=timestamp_to_iso(min_ts),
        max_timestamp=max_ts,
        max_time=timestamp_to_iso(max_ts),
        transfer_like_rows=transfer_like,
        usdt_transfer_rows=usdt_transfer,
    )


def decode_stablecoin_transfers(csv_path: Path | str, output_jsonl: Path | str, max_rows: int | None = None) -> dict:
    output_path = Path(output_jsonl)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows_seen = 0
    transfers = 0
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        for row in iter_raw_rows(csv_path):
            rows_seen += 1
            transfer = decode_transfer_row(row)
            if transfer is not None:
                fh.write(json.dumps(asdict(transfer), ensure_ascii=False) + "\n")
                transfers += 1
            if max_rows is not None and rows_seen >= max_rows:
                break
    return {"input": str(csv_path), "output": str(output_path), "rows_seen": rows_seen, "transfers": transfers}


def iter_transfer_jsonl(path: Path | str) -> Iterable[dict]:
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def transfer_to_chain_event(transfer: dict, direction: str = "chain_transfer") -> dict:
    txid = str(transfer.get("txid") or "")
    event_id = str(transfer.get("event_id") or f"tx_{txid}")
    return {
        "event_id": event_id,
        "event_class": "chain_transfer",
        "direction": direction,
        "asset": transfer.get("asset", "USDT"),
        "quantity": str(transfer.get("amount") or "0"),
        "time": transfer.get("time") or transfer.get("time_utc"),
        "time_utc": transfer.get("time_utc") or transfer.get("time"),
        "time_local": transfer.get("time_local"),
        "txid": txid,
        "address": transfer.get("to_address"),
        "counterparty": transfer.get("from_address"),
        "block_number": transfer.get("block_number"),
        "timestamp": transfer.get("timestamp"),
        "token_contract": transfer.get("token_contract"),
        "direction_hint": transfer.get("direction_hint", "unknown"),
    }


def load_transfer_events(jsonl_paths: Iterable[Path | str], direction: str = "chain_transfer") -> list[dict]:
    events: list[dict] = []
    for path in jsonl_paths:
        for transfer in iter_transfer_jsonl(path):
            if direction == "both":
                events.append(transfer_to_chain_event(transfer, direction="chain_withdrawal"))
                events.append(transfer_to_chain_event(transfer, direction="chain_deposit"))
            else:
                events.append(transfer_to_chain_event(transfer, direction=direction))
    events.sort(key=lambda item: item.get("time") or "")
    return events


def discover_transfer_files(root: Path | str, suffix: str = ".jsonl") -> list[Path]:
    base = Path(root)
    if base.is_file():
        return [base]
    return sorted(path for path in base.rglob(f"*{suffix}") if path.is_file())


def query_transfer_window(
    jsonl_paths: Iterable[Path | str],
    start_time: datetime,
    end_time: datetime,
    asset: str = "USDT",
    direction: str = "chain_transfer",
    amount_upper: Decimal | None = None,
) -> list[dict]:
    events: list[dict] = []
    for path in jsonl_paths:
        for transfer in iter_transfer_jsonl(path):
            if transfer.get("asset") != asset:
                continue
            event = transfer_to_chain_event(transfer, direction=direction)
            if not event.get("time"):
                continue
            event_ts = datetime.strptime(str(event["time"]), "%Y-%m-%d %H:%M:%S")
            if event_ts < start_time or event_ts > end_time:
                continue
            if amount_upper is not None and Decimal(str(event["quantity"])) > amount_upper:
                continue
            events.append(event)
    events.sort(key=lambda item: item["time"])
    return events


def window_for_anchor(anchor: dict, label_type: str, window_days: int) -> tuple[datetime, datetime, str]:
    anchor_time = datetime.strptime(str(anchor["time"]), "%Y-%m-%d %H:%M:%S")
    if label_type == "fiat_buy_to_chain_withdrawal":
        return anchor_time, anchor_time + timedelta(days=window_days), "chain_withdrawal"
    if label_type == "fiat_sell_to_chain_deposit":
        return anchor_time - timedelta(days=window_days), anchor_time, "chain_deposit"
    raise ValueError(f"unsupported label_type: {label_type}")


def write_json(path: Path | str, payload: object) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_raw_manifest(input_paths: Iterable[Path | str], output_path: Path | str, max_rows_per_file: int | None = None) -> dict:
    files = []
    for input_path in input_paths:
        stats = inspect_raw_csv(input_path, max_rows=max_rows_per_file)
        files.append(asdict(stats))
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "time_standard": "UTC naive ISO strings derived from millisecond timestamps",
        "max_rows_per_file": max_rows_per_file,
        "files": files,
    }
    write_json(output_path, manifest)
    return manifest
