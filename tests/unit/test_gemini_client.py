"""เทส app/external/gemini_client.py — เฉพาะการ parse คำตอบ (ไม่ยิง Gemini จริง)

★ ไม่เชื่อรูปร่างคำตอบ AI: JSON เพี้ยน/ชนิดผิด ต้องกลายเป็น None ไม่ใช่พังทั้งงาน
"""
import pytest

from app.external.gemini_client import GeminiClient, _as_date, _as_float


def test_requires_api_key():
    with pytest.raises(ValueError):
        GeminiClient(api_key="")


def test_parse_valid_json():
    fields = GeminiClient._parse(
        '{"total_amount": 149.0, "receipt_date": "2026-06-06", '
        '"merchant_name": "KFC", "confidence": 0.9}'
    )
    assert fields.total_amount == 149.0
    assert fields.receipt_date.isoformat() == "2026-06-06"
    assert fields.merchant_name == "KFC"
    assert fields.confidence == 0.9


def test_parse_null_values():
    fields = GeminiClient._parse('{"total_amount": null, "receipt_date": null}')
    assert fields.total_amount is None
    assert fields.receipt_date is None


def test_parse_non_json_does_not_crash():
    """★ AI ตอบไม่ใช่ JSON (คำอธิบายยาวๆ) → เดาไม่ออก ไม่ใช่พัง"""
    fields = GeminiClient._parse("ขอโทษครับ ผมอ่านใบเสร็จนี้ไม่ออก")
    assert fields.total_amount is None


def test_parse_wrong_type_becomes_none():
    """total_amount เป็น string ที่ไม่ใช่ตัวเลข → None ไม่ใช่ throw"""
    fields = GeminiClient._parse('{"total_amount": "เยอะมาก"}')
    assert fields.total_amount is None


def test_parse_json_array_not_object():
    """AI คืน array แทน object → ไม่พัง"""
    assert GeminiClient._parse("[1, 2, 3]").total_amount is None


def test_as_float_handles_string_number():
    assert _as_float("149.0") == 149.0
    assert _as_float(None) is None
    assert _as_float("abc") is None


def test_as_date_handles_bad_format():
    assert _as_date("2026-06-06").isoformat() == "2026-06-06"
    assert _as_date("06/06/2026") is None  # รูปแบบผิด → None
    assert _as_date(12345) is None
