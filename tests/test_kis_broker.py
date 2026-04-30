from __future__ import annotations

import pytest

from mimmy.trading.kis import KISClient, _parse_price, parse_ccld_for_odno, tr_id


# ─── tr_id 매핑 — 실계좌/모의투자 혼동을 막기 위한 가장 중요한 테스트 ───


def test_tr_id_paper_vs_live_distinct():
    assert tr_id("paper", "buy") == "VTTC0802U"
    assert tr_id("paper", "sell") == "VTTC0801U"
    assert tr_id("live", "buy") == "TTTC0802U"
    assert tr_id("live", "sell") == "TTTC0801U"
    # 실계좌와 모의계좌 tr_id는 절대 겹치면 안 된다
    for op in ("buy", "sell", "cancel"):
        assert tr_id("paper", op) != tr_id("live", op)


def test_tr_id_cancel():
    assert tr_id("paper", "cancel") == "VTTC0803U"
    assert tr_id("live", "cancel") == "TTTC0803U"


def test_tr_id_price_shared():
    assert tr_id("paper", "price") == tr_id("live", "price") == "FHKST01010100"


def test_tr_id_ccld_paper_vs_live_distinct():
    assert tr_id("paper", "ccld") == "VTTC8001R"
    assert tr_id("live", "ccld") == "TTTC8001R"
    assert tr_id("paper", "ccld") != tr_id("live", "ccld")


# ─── KISClient 생성자 검증 ───


def test_kis_client_requires_account_format():
    with pytest.raises(ValueError, match="12345678-01"):
        KISClient(
            env="paper",
            app_key="k",
            app_secret="s",
            account_no="12345678",  # '-' 없음
        )


def test_kis_client_requires_creds():
    with pytest.raises(ValueError):
        KISClient(env="paper", app_key="", app_secret="", account_no="12345678-01")


def test_kis_client_rejects_unknown_env():
    with pytest.raises(ValueError, match="unknown KIS env"):
        KISClient(
            env="prod",  # type: ignore[arg-type]
            app_key="k",
            app_secret="s",
            account_no="12345678-01",
        )


def test_kis_client_parses_account():
    c = KISClient(
        env="paper",
        app_key="k",
        app_secret="s",
        account_no="12345678-01",
    )
    assert c.cano == "12345678"
    assert c.acnt_prdt_cd == "01"


# ─── 가격 파싱 ───


def test_parse_price_from_stck_prpr():
    assert _parse_price({"stck_prpr": "72500"}) == 72500.0


def test_parse_price_uppercase_key():
    assert _parse_price({"STCK_PRPR": "72500"}) == 72500.0


def test_parse_price_missing():
    assert _parse_price({}) is None
    assert _parse_price({"other": "x"}) is None


def test_parse_price_malformed():
    assert _parse_price({"stck_prpr": "not a number"}) is None


# ─── ccld 파싱 ───


def _ccld_row(odno: str, filled: int, avg: str, remaining: int = 0, cancelled: int = 0):
    return {
        "odno": odno,
        "tot_ccld_qty": str(filled),
        "avg_prvs": avg,
        "rmn_qty": str(remaining),
        "cncld_qty": str(cancelled),
    }


def test_ccld_filters_by_odno():
    payload = {
        "output1": [
            _ccld_row("111", 10, "70000"),
            _ccld_row("222", 5, "72000"),
        ]
    }
    r = parse_ccld_for_odno(payload, odno="222")
    assert r["filled_qty"] == 5
    assert r["avg_price"] == 72000.0


def test_ccld_weighted_average():
    """2건이 다른 가격에 체결 → 수량 가중평균이어야 한다."""
    payload = {
        "output1": [
            _ccld_row("111", 10, "70000"),
            _ccld_row("111", 20, "71000"),
        ]
    }
    r = parse_ccld_for_odno(payload, odno="111")
    assert r["filled_qty"] == 30
    # (10*70000 + 20*71000) / 30 = 70666.666...
    assert abs(r["avg_price"] - (10 * 70000 + 20 * 71000) / 30) < 0.01


def test_ccld_handles_uppercase_keys():
    payload = {"output1": [{"ODNO": "111", "TOT_CCLD_QTY": "7", "AVG_PRVS": "70000"}]}
    r = parse_ccld_for_odno(payload, odno="111")
    assert r["filled_qty"] == 7
    assert r["avg_price"] == 70000.0


def test_ccld_empty_payload():
    r = parse_ccld_for_odno({}, odno="111")
    assert r["filled_qty"] == 0
    assert r["avg_price"] == 0.0
    assert r["remaining_qty"] == 0


def test_ccld_remaining_and_cancelled():
    payload = {"output1": [_ccld_row("111", 3, "70000", remaining=2, cancelled=5)]}
    r = parse_ccld_for_odno(payload, odno="111")
    assert r["remaining_qty"] == 2
    assert r["cancelled_qty"] == 5


def test_ccld_comma_in_numbers():
    """KIS 응답이 천단위 콤마를 포함할 수 있다."""
    payload = {"output1": [{"odno": "111", "tot_ccld_qty": "1,000", "avg_prvs": "70,500"}]}
    r = parse_ccld_for_odno(payload, odno="111")
    assert r["filled_qty"] == 1000
    assert r["avg_price"] == 70500.0


def test_ccld_falls_back_to_avg_ord_unpr():
    payload = {
        "output1": [
            {"odno": "111", "tot_ccld_qty": "5", "avg_ord_unpr": "70000"},
        ]
    }
    r = parse_ccld_for_odno(payload, odno="111")
    assert r["avg_price"] == 70000.0
