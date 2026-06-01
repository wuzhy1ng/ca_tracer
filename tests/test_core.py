from __future__ import annotations

from algos.baseline import MatchResult, exact_hit
from daos.tron import decode_tron_address_word


def test_decode_tron_address_word_with_tron_prefix() -> None:
    word = "000000000000000000000041206e7149ff212e32d6d8fb733d9cf42fead1b2ca"
    assert decode_tron_address_word(word) == "41206e7149ff212e32d6d8fb733d9cf42fead1b2ca"


def test_decode_tron_address_word_without_tron_prefix() -> None:
    word = "000000000000000000000000206e7149ff212e32d6d8fb733d9cf42fead1b2ca"
    assert decode_tron_address_word(word) == "41206e7149ff212e32d6d8fb733d9cf42fead1b2ca"


def test_exact_hit_prefers_txid_match() -> None:
    result = MatchResult(candidate_ids=["tx_abc"], candidate_txids=["abc"], score=1.0)
    assert exact_hit([result], truth_ids={"evt_1"}, truth_txids={"abc"}, k=1)


def test_exact_hit_falls_back_to_event_id() -> None:
    result = MatchResult(candidate_ids=["evt_1"], score=1.0)
    assert exact_hit([result], truth_ids={"evt_1"}, truth_txids=set(), k=1)
