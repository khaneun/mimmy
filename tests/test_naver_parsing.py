from __future__ import annotations

from mimmy.core.types import Instrument, InstrumentKind, MarketCode, Ticker
from mimmy.data.sources.naver_finance import parse_news_json, parse_quote_json


def _samsung_common() -> Instrument:
    t = Ticker(market=MarketCode.KR, symbol="005930", name="삼성전자")
    return Instrument(ticker=t, kind=InstrumentKind.COMMON, symbol="005930")


def test_parse_quote_basic():
    payload = {
        "resultCode": "success",
        "result": {
            "pollingInterval": 30000,
            "areas": [
                {
                    "name": "SERVICE_ITEM",
                    "datas": [
                        {
                            "cd": "005930",
                            "nm": "삼성전자",
                            "nv": 72500,
                            "cv": 500,
                            "cr": 0.70,
                            "sv": 72000,
                            "hv": 73000,
                            "lv": 71900,
                            "aq": 12345678,
                            "aa": 890123456789,
                        }
                    ],
                }
            ],
        },
    }
    q = parse_quote_json(payload, _samsung_common())
    assert q is not None
    assert q.last == 72500.0
    assert q.volume == 12345678.0
    assert q.bid is None and q.ask is None


def test_parse_quote_symbol_mismatch_returns_none():
    payload = {
        "result": {
            "areas": [{"datas": [{"cd": "000660", "nv": 200_000}]}],
        }
    }
    assert parse_quote_json(payload, _samsung_common()) is None


def test_parse_quote_empty_areas():
    assert parse_quote_json({"result": {"areas": []}}, _samsung_common()) is None
    assert parse_quote_json({}, _samsung_common()) is None


def test_parse_news_list_form():
    ticker = Ticker(market=MarketCode.KR, symbol="005930", name="삼성전자")
    payload = [
        {
            "title": "삼성전자, 2분기 영업이익 10조 돌파",
            "linkUrl": "https://n.news.naver.com/article/0001",
            "officeName": "한국경제",
            "datetime": "20260421093000",
            "summary": "삼성전자가 2분기에...",
        },
        {
            "title": "반도체 업황 바닥 탈출 신호",
            "linkUrl": "https://n.news.naver.com/article/0002",
            "officeName": "매일경제",
            "datetime": "20260421084500",
        },
    ]
    items = parse_news_json(payload, ticker)
    assert len(items) == 2
    assert items[0].headline.startswith("삼성전자")
    assert items[0].source == "한국경제"
    assert items[0].published_at.year == 2026
    assert items[1].body is None


def test_parse_news_dict_wrapped():
    ticker = Ticker(market=MarketCode.KR, symbol="005930")
    payload = {"items": [{"title": "x", "linkUrl": "u", "officeName": "s", "datetime": "20260421"}]}
    items = parse_news_json(payload, ticker)
    assert len(items) == 1
    assert items[0].headline == "x"


def test_parse_news_ignores_malformed():
    ticker = Ticker(market=MarketCode.KR, symbol="005930")
    payload = [{"no_title_here": True}, "not a dict", {"title": "ok", "officeName": "s"}]
    items = parse_news_json(payload, ticker)
    assert len(items) == 1
    assert items[0].headline == "ok"
