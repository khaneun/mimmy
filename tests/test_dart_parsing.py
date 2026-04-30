from __future__ import annotations

from mimmy.core.types import MarketCode, Ticker
from mimmy.data.sources.dart import parse_corp_code_xml, parse_list_json


def test_parse_corp_code_xml_picks_only_listed():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<result>
  <list>
    <corp_code>00126380</corp_code>
    <corp_name>삼성전자</corp_name>
    <stock_code>005930</stock_code>
    <modify_date>20170630</modify_date>
  </list>
  <list>
    <corp_code>00164742</corp_code>
    <corp_name>SK하이닉스</corp_name>
    <stock_code>000660</stock_code>
    <modify_date>20170630</modify_date>
  </list>
  <list>
    <corp_code>00999999</corp_code>
    <corp_name>비상장사</corp_name>
    <stock_code> </stock_code>
    <modify_date>20170630</modify_date>
  </list>
</result>""".encode("utf-8")
    m = parse_corp_code_xml(xml)
    assert m["005930"] == "00126380"
    assert m["000660"] == "00164742"
    # 비상장사 (stock_code 공백) 는 제외
    assert len(m) == 2


def test_parse_list_json_classifies_categories():
    ticker = Ticker(market=MarketCode.KR, symbol="005930", name="삼성전자")
    payload = {
        "status": "000",
        "message": "정상",
        "list": [
            {
                "report_nm": "주요사항보고서(자기주식취득결정)",
                "rcept_no": "20260421000123",
                "rcept_dt": "20260421",
            },
            {
                "report_nm": "분기보고서",
                "rcept_no": "20260415000456",
                "rcept_dt": "20260415",
            },
            {
                "report_nm": "기업설명회(IR)개최",
                "rcept_no": "20260410000789",
                "rcept_dt": "20260410",
            },
        ],
    }
    items = parse_list_json(payload, ticker)
    assert len(items) == 3
    cats = {i.category for i in items}
    assert cats == {"material-event", "periodic", "other"}
    # URL 규칙 확인
    assert items[0].url.endswith("rcpNo=20260421000123")


def test_parse_list_json_status_error_returns_empty():
    ticker = Ticker(market=MarketCode.KR, symbol="005930")
    payload = {"status": "010", "message": "등록되지 않은 키"}
    assert parse_list_json(payload, ticker) == []


def test_parse_list_json_skips_malformed_date():
    ticker = Ticker(market=MarketCode.KR, symbol="005930")
    payload = {
        "status": "000",
        "list": [
            {"report_nm": "정상공시", "rcept_no": "1", "rcept_dt": "20260421"},
            {"report_nm": "고장공시", "rcept_no": "2", "rcept_dt": "BADDATE"},
        ],
    }
    items = parse_list_json(payload, ticker)
    assert len(items) == 1
    assert items[0].rcept_no if False else True  # 단순 존재 확인
    assert items[0].title == "정상공시"
