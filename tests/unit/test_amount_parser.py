"""เทส app/receipt_data/amount_parser.py + total_finder.py

★ ทุกเคสในไฟล์นี้มาจากใบเสร็จจริงที่เก็บมา ไม่ใช่ตัวอย่างสมมติ
  ชื่อเทสจึงบอกด้วยว่า "เจอจากใบไหน" เพื่อให้คนแก้ทีหลังรู้ว่าทำไมกฎนี้ถึงมีอยู่
"""
import pytest

from app.receipt_data.amount_parser import best_amount, find_amounts
from app.receipt_data.total_finder import find_total


# ═══════════════════════════════════════════
# ★ สิ่งที่ "หน้าตาเหมือนเงินแต่ไม่ใช่" — อ่านผิดตรงนี้ = แต้มผิด
# ═══════════════════════════════════════════

def test_time_is_not_money():
    """สลิปบัตร KFC: '17:25.14' เคยถูกอ่านเป็นยอด 25.14 บาท (ยอดจริง 528)"""
    assert best_amount("17:25.14") is None
    assert best_amount("APPR.CODE#636282 17:25.14") is None


def test_date_is_not_money():
    assert best_amount("06/06/2569 13:42") is None
    assert best_amount("Jun 6, 2026") is None, "ปี 2026 ต้องไม่กลายเป็นยอด 2,026 บาท"


def test_long_reference_number_is_not_money():
    assert best_amount("TRANS ID 003646335301") is None
    assert best_amount("TAX ID: 0105532021090") is None


def test_digits_glued_to_letters_are_rejected():
    """KFC: OCR อ่าน 'Total 149.00' เป็น 'Tota114900'
    ของเดิมตัดเป็น 114+900 แล้วให้ยอด 900 (ผิดจากจริง 149 ถึง 6 เท่า)
    ตอนนี้ต้องคืน None — ยอมอ่านไม่ได้ ดีกว่าเดาผิด"""
    assert best_amount("Tota114900") is None


# ═══════════════════════════════════════════
# รูปแบบเงินที่ OCR อ่านเพี้ยน แต่ยังกู้ได้
# ═══════════════════════════════════════════

def test_dash_as_decimal_separator():
    """KFC: เครื่องพิมพ์ความร้อนทำให้จุดกลายเป็นขีด '528-00'"""
    assert best_amount("528-00") == 528.00


def test_comma_with_only_two_digits_is_rejected_as_ambiguous():
    """★ Pizza Company: ยอด "2,696" ถูก OCR อ่านตกเป็น "2,69"
    ถ้าตีความจุลภาคเป็นจุดทศนิยมจะได้ 2.69 บาท ทั้งที่จริง 2,696 (ผิด 1,000 เท่า)

    บนใบเสร็จไทยจุลภาคคือตัวคั่นหลักพัน ต้องตามด้วย 3 หลักเสมอ
    เจอ 2 หลัก = อ่านตก → ปฏิเสธ ไม่เดา"""
    assert best_amount("Total 2,69") is None
    assert best_amount("รวม 528,00") is None


def test_proper_thousand_separator_still_works():
    assert best_amount("Subtotal 2,696") == 2696.00
    assert best_amount("Total 1,240.00") == 1240.00


def test_currency_prefix_glued_to_number():
    """สลิปธนาคารกรุงเทพ: 'THB528.00' ติดกันไม่มีช่องว่าง"""
    assert best_amount("THB528.00") == 528.00
    assert best_amount("Total THB528.00") == 528.00


def test_thousand_separator():
    assert best_amount("Total 1,240") == 1240.00
    assert best_amount("รวมทั้งสิ้น 2,696.00") == 2696.00


# ═══════════════════════════════════════════
# เลือกตัวไหนเมื่อมีหลายตัวเลขในบรรทัด
# ═══════════════════════════════════════════

def test_prefers_amount_with_decimals_over_bare_number():
    """'VAT 7% 16.36' — 7 คือเปอร์เซ็นต์ ไม่ใช่เงิน"""
    assert best_amount("VAT 7% 16.36") == 16.36


def test_prefers_amount_with_currency_marker():
    assert best_amount("100 บาท 250.00") == 250.00


def test_zero_is_rejected():
    """ยอด 0 บาทคือ OCR อ่านพลาด ไม่ใช่ใบเสร็จจริง"""
    assert best_amount("TOTAL 0.00") is None


def test_no_amount_returns_none():
    assert best_amount("ขอบคุณที่ใช้บริการ") is None
    assert find_amounts("") == []


# ═══════════════════════════════════════════
# ★ ตรวจคณิตศาสตร์ — ยอดย่อย + VAT = ยอดรวม
# ═══════════════════════════════════════════

def test_math_confirms_keyword():
    """สองชั้นตรงกัน = มั่นใจสูงสุด"""
    lines = ["TEST SHOP", "SUBTOTAL 233.64", "VAT 7% 16.36", "TOTAL 250.00"]
    result = find_total(lines, keyword_total=250.00)

    assert result.value == 250.00
    assert result.score == 100


def test_math_recovers_total_when_label_unreadable():
    """★ ใบ V-Square: ป้าย 'ยอดสุทธิ' จางจน OCR อ่านไม่เจอ
    แต่ 32.71 + 2.29 = 35.00 ยังบอกเราได้ว่ายอดคือ 35"""
    lines = ["V-Square Department Store", "35.00", "100.00", "65.00", "2.29", "32.71"]
    result = find_total(lines, keyword_total=None)

    assert result is not None
    assert result.value == 35.00


def test_math_wins_when_it_disagrees_with_keyword():
    """คำอาจอ่านเพี้ยน แต่สมการปลอมยาก → เชื่อสมการ"""
    lines = ["SHOP", "SUBTOTAL 233.64", "VAT 16.36", "TOTAL 250.00"]
    result = find_total(lines, keyword_total=233.64)  # จับคำผิดไปโดน subtotal

    assert result.value == 250.00


def test_keyword_alone_still_works():
    """ใบเสร็จที่ไม่แยก VAT (ร้านเล็ก) — ยังต้องอ่านได้จากคำสำคัญ"""
    result = find_total(["ร้านกาแฟ", "รวมทั้งสิ้น 60.00"], keyword_total=60.00)
    assert result.value == 60.00


def test_returns_none_when_no_evidence():
    assert find_total(["ขอบคุณที่ใช้บริการ"], keyword_total=None) is None


def test_vat_must_actually_be_seven_percent():
    """กันบังเอิญ: a+b=c ที่ b ไม่ใช่ VAT 7% ต้องไม่ถูกนับ
    (เช่น 100 + 50 = 150 เป็นเลขบังเอิญ ไม่ใช่โครงสร้างภาษี)"""
    lines = ["SHOP", "100.00", "50.00", "150.00"]
    assert find_total(lines, keyword_total=None) is None


# ═══════════════════════════════════════════
# กฎเฉพาะที่ค้นพบจากใบเสร็จจริง (แต่ละข้อกู้ได้อย่างน้อย 1 ใบ)
# ═══════════════════════════════════════════

def test_currency_marked_amount_used_when_keyword_lost():
    """สลิป QR PromptPay ของ KFC: คำว่า Total หลุดไปคนละบรรทัดกับยอด
    แต่ "THB528.00" บอกตัวเองอยู่แล้วว่าเป็นเงิน"""
    lines = [
        "BIG C NAKORNSAWAN KFC-12102",
        "APPR.CODE#636282 TRACE#071045 17:25.14",
        "REF#2 47853174225684071045 THB528.00",
        "Total IACKNOWLEDCE SAIISTACTORY RECEIPT",
    ]
    result = find_total(lines, keyword_total=None)
    assert result.value == 528.00


def test_subtotal_used_when_total_line_is_unusable():
    """Pizza Company: "Total 2,69" อ่านตกหลักจนใช้ไม่ได้
    แต่ "Subtotal 2,696" ถูกต้อง และใบนี้ VAT รวมในราคาแล้ว"""
    lines = ["PIZZA COMPANY", "Subtotal 2,696", "Total 2,69"]
    result = find_total(lines, keyword_total=None)
    assert result.value == 2696.00


def test_subtotal_not_used_when_vat_is_separate():
    """★ ถ้าใบเสร็จแยกบรรทัด VAT ไว้ ยอดย่อยไม่ใช่ยอดที่จ่ายจริง
    (ต้องบวก VAT เพิ่ม) — ห้ามใช้ยอดย่อยแทน"""
    lines = ["SHOP", "Subtotal 100.00", "VAT 7% 7.00"]
    result = find_total(lines, keyword_total=None)
    assert result is None or result.value != 100.00


# ═══════════════════════════════════════════
# สลิปบัตรเติมเงิน (BigC FoodPark)
# ═══════════════════════════════════════════

def test_card_slip_uses_subtraction_over_shifted_label():
    """ป้าย "Sale Amount" จับคู่กับตัวเลขเหลื่อมแถวเมื่อถ่ายเอียง (ได้ 225 ทั้งที่จ่าย 75)
    การลบ 300 − 75 = 225 ให้คำตอบที่ถูก และเหลื่อมยังไงก็ยังลงตัวเหมือนเดิม"""
    lines = [
        "BIGC SUPERCENTER", "Card Balance", "300.00",
        "Sale Anmount", "75.00", "Card Net Balance", "225.00",
    ]
    result = find_total(lines, keyword_total=225.00)
    assert result.value == 75.00


def test_card_slip_falls_back_to_footer_line():
    """ลบไม่ลงตัว (OCR อ่านตก) → ใช้บรรทัดท้าย "Card No:xxx AMT: yyy"
    ซึ่งมีป้ายกับตัวเลขอยู่แถวเดียวกัน จึงไม่มีปัญหาคอลัมน์เหลื่อม"""
    lines = [
        "FOODPark BIG C", "Cad Balance AMT: 35.00", "Sale Amount AMT: 35.00",
        "Card Net Balance", "Card No:3210019969783 AMT 10.00",
    ]
    result = find_total(lines, keyword_total=35.00)
    assert result.value == 10.00
