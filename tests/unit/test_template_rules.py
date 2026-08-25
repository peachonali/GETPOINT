"""เทส app/merchant/template_rules.py — กฎตรวจค่าที่ดึงมา

★ กฎชุดนี้ต้อง "ไม่ผ่านของที่ผิด" และ "ไม่ตีตกของที่ถูก" พร้อมกัน
  ทิศทางของความผิดพลาด: บอกว่า "ยืนยันแล้ว" ทั้งที่อ่านผิด แย่ที่สุด
  (เพราะชั้นบนจะเชื่อแล้วให้แต้ม) → math_confirmed ต้องเข้มจริง
"""
from datetime import date

from app.merchant.template_rules import validate
from app.receipt_data.line_items import LineItem

TODAY = date(2026, 6, 10)


def _validate(**kw):
    kw.setdefault("receipt_date", date(2026, 6, 6))
    kw.setdefault("line_items", [])
    kw.setdefault("today", TODAY)
    return validate(**kw)


# ═══════════════════════════════════════════
# กฎคณิตศาสตร์ — ผลรวมรายการ = ยอดรวม
# ═══════════════════════════════════════════

def test_math_confirmed_when_items_sum_to_total():
    """ใบ KFC 528 จริง: 449 + 20 + 59 = 528"""
    items = [LineItem("New Suk Jai", 449.0), LineItem("fries", 20.0), LineItem("roll", 59.0)]
    result = _validate(total_amount=528.0, line_items=items)
    assert result.math_confirmed


def test_math_not_confirmed_when_a_price_misread():
    """★ อ่านราคาผิดตัวเดียว กฎต้องไม่ยืนยัน — นี่คือประโยชน์ทั้งหมดของชั้นนี้"""
    items = [LineItem("New Suk Jai", 449.0), LineItem("fries", 20.0), LineItem("roll", 60.0)]
    result = _validate(total_amount=528.0, line_items=items)
    assert not result.math_confirmed
    assert "line_items_sum_to_total" in result.failed_checks


def test_math_skipped_when_no_priced_items():
    """ชุดเซ็ตที่ของในชุดไม่มีราคา / อ่านรายการไม่ได้ → skip ไม่ใช่ fail

    การอ่านรายการไม่ได้ ไม่ได้แปลว่ายอดรวมผิด
    """
    result = _validate(total_amount=149.0, line_items=[LineItem("BOX", None)])
    assert not result.math_confirmed
    assert "line_items_sum_to_total" in result.skipped_checks
    assert not result.has_hard_failure


def test_set_menu_total_matches_first_priced_line():
    """ชุดเซ็ต KFC: รายการแรกมีราคา = ยอดรวม ที่เหลือไม่มีราคา"""
    items = [LineItem("BOX All Easy", 149.0), LineItem("CrispyStrip", None)]
    assert _validate(total_amount=149.0, line_items=items).math_confirmed


# ═══════════════════════════════════════════
# กฎยอดในช่วง — hard failure
# ═══════════════════════════════════════════

def test_total_out_of_range_is_hard_failure():
    """ยอด 0 หรือติดลบ = อ่านเพี้ยนแน่นอน ต้องไม่เชื่อ"""
    assert _validate(total_amount=0.0).has_hard_failure
    assert "total_in_range" in _validate(total_amount=999_999.0).failed_checks


def test_normal_total_passes_range():
    assert "total_in_range" in _validate(total_amount=149.0).passed_checks


# ═══════════════════════════════════════════
# กฎวันที่
# ═══════════════════════════════════════════

def test_future_date_is_hard_failure():
    """★ ใบเสร็จจากอนาคต = OCR อ่านวันที่ผิด (เจอจริง: อ่านปี 2069)"""
    result = _validate(total_amount=100.0, receipt_date=date(2027, 1, 1))
    assert result.has_hard_failure
    assert "date_not_in_future" in result.failed_checks


def test_today_receipt_passes():
    assert "date_not_in_future" in _validate(total_amount=100.0, receipt_date=TODAY).passed_checks


def test_very_old_receipt_fails_but_is_not_hard():
    """ใบเก่าเกินไปน่าสงสัย แต่ไม่ใช่ hard failure (อาจเป็นใบเก่าจริงที่ลูกค้าเพิ่งสแกน)"""
    result = _validate(total_amount=100.0, receipt_date=date(2024, 1, 1))
    assert "date_not_too_old" in result.failed_checks
    assert not result.has_hard_failure


def test_no_date_is_skipped_not_failed():
    """อ่านวันที่ไม่ได้ = ไม่ใช่ทุกใบมีวันที่ → skip ไม่ใช่ fail"""
    result = _validate(total_amount=100.0, receipt_date=None)
    assert "date_not_in_future" in result.skipped_checks
    assert not result.has_hard_failure


# ═══════════════════════════════════════════
# VAT แยกบรรทัด
# ═══════════════════════════════════════════

def test_subtotal_plus_vat_confirmed():
    """ยอดย่อย 100 + VAT 7 = 107"""
    items = [LineItem("สินค้า", 100.0), LineItem("VAT", 7.0)]
    assert "subtotal_plus_vat" in _validate(total_amount=107.0, line_items=items).passed_checks


def test_vat_skipped_when_included_in_price():
    """ใบเสร็จไทยส่วนใหญ่รวม VAT แล้ว (ไม่มีบรรทัด VAT แยก) → skip"""
    result = _validate(total_amount=100.0, line_items=[LineItem("สินค้า", 100.0)])
    assert "subtotal_plus_vat" in result.skipped_checks
