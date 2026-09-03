"""เทส app/receipt_data/field_extractor.py

ตัวอ่านค่าแบบเดาจากคำสำคัญ (เวอร์ชัน Step 3) — Step 5 จะแทนด้วย template
เทสชุดนี้ตรึง "พฤติกรรมที่คาดหวัง" ไว้ เพื่อให้ตอนเปลี่ยนไปใช้ template
รู้ได้ว่าเคสไหนเคยทำได้บ้าง (กันของที่เคยดีกลับแย่ลง)
"""
from datetime import date

import pytest

from app.ocr.ocr_result import OcrResult, TextBox
from app.receipt_data.field_extractor import extract_receipt_fields
from app.reliability.errors import InputValidationError


def _ocr(*lines: str) -> OcrResult:
    return OcrResult(boxes=[TextBox(text=line, bbox=(0, i * 40, 300, i * 40 + 30))
                            for i, line in enumerate(lines)])


# ═══════════════════════════════════════════
# ยอดเงิน — สำคัญที่สุด (ผิด = แต้มผิด)
# ═══════════════════════════════════════════

def test_reads_total_from_thai_keyword():
    fields = extract_receipt_fields(_ocr("ร้านทดสอบ", "รวมทั้งสิ้น 250.00"))
    assert fields["total_amount"] == 250.00


def test_reads_total_with_thousand_separator():
    fields = extract_receipt_fields(_ocr("ร้าน", "ยอดสุทธิ 1,234.56"))
    assert fields["total_amount"] == 1234.56


def test_ignores_percent_number_in_vat_line():
    """'ภาษีมูลค่าเพิ่ม 7% 16.36' — ต้องได้ 16.36 ไม่ใช่ 7
    (เอาเลขตัวสุดท้ายของบรรทัด ไม่ใช่ตัวแรก)"""
    fields = extract_receipt_fields(_ocr("ร้าน", "total 7% 16.36"))
    assert fields["total_amount"] == 16.36


def test_prefers_specific_keyword_over_generic():
    """ใบเสร็จมีทั้ง 'ยอดรวม' (ก่อน VAT) และ 'รวมทั้งสิ้น' (สุดท้าย)
    ต้องเลือกตัวที่เจาะจงกว่า = ยอดที่ลูกค้าจ่ายจริง"""
    fields = extract_receipt_fields(_ocr(
        "ร้านทดสอบ", "ยอดรวม 233.64", "ภาษี 16.36", "รวมทั้งสิ้น 250.00",
    ))
    assert fields["total_amount"] == 250.00


def test_reads_english_total():
    assert extract_receipt_fields(_ocr("Shop", "Grand Total 99.50"))["total_amount"] == 99.50


def test_missing_total_raises_instead_of_guessing():
    """★ กฎเหล็ก: อ่านยอดไม่ได้ = ล้มเหลว ห้ามเดาจากเลขที่ใหญ่สุดในใบ
    (ให้แต้มผิดเสียหายกว่าไม่ให้แต้ม)"""
    with pytest.raises(InputValidationError):
        extract_receipt_fields(_ocr("ร้านทดสอบ", "ขอบคุณที่ใช้บริการ", "123456789"))


def test_empty_ocr_raises():
    with pytest.raises(InputValidationError):
        extract_receipt_fields(_ocr())


# ═══════════════════════════════════════════
# เลขที่ใบเสร็จ + วันที่ (ใช้ทำ fingerprint กันใบซ้ำ)
# ═══════════════════════════════════════════

def test_reads_receipt_no():
    fields = extract_receipt_fields(_ocr("ร้าน", "เลขที่ INV-0001", "รวมทั้งสิ้น 100"))
    assert fields["receipt_no"] == "INV-0001"


def test_receipt_no_is_optional():
    fields = extract_receipt_fields(_ocr("ร้าน", "รวมทั้งสิ้น 100"))
    assert fields["receipt_no"] is None


def test_reads_gregorian_date():
    fields = extract_receipt_fields(_ocr("ร้าน", "วันที่ 01/08/2026", "รวมทั้งสิ้น 100"))
    assert fields["receipt_date"] == date(2026, 8, 1)


def test_converts_buddhist_year():
    """ใบเสร็จไทยส่วนใหญ่พิมพ์ปี พ.ศ. — ต้องแปลงเป็น ค.ศ. ไม่งั้นวันที่เพี้ยน 543 ปี"""
    fields = extract_receipt_fields(_ocr("ร้าน", "วันที่ 01/08/2569", "รวมทั้งสิ้น 100"))
    assert fields["receipt_date"] == date(2026, 8, 1)


def test_handles_two_digit_year():
    fields = extract_receipt_fields(_ocr("ร้าน", "01-08-26", "รวมทั้งสิ้น 100"))
    assert fields["receipt_date"] == date(2026, 8, 1)


def test_invalid_date_is_skipped_not_crashing():
    """OCR อ่านวันที่เพี้ยน (32/13/2026) — ต้องข้ามไป ไม่ใช่พังทั้งงาน"""
    fields = extract_receipt_fields(_ocr("ร้าน", "วันที่ 32/13/2026", "รวมทั้งสิ้น 100"))
    assert fields["receipt_date"] is None
    assert fields["total_amount"] == 100


# ═══════════════════════════════════════════
# ชื่อร้าน
# ═══════════════════════════════════════════

def test_merchant_is_first_line():
    fields = extract_receipt_fields(_ocr("ร้านทดสอบ สาขาทดลอง", "รวมทั้งสิ้น 100"))
    assert fields["merchant"] == "ร้านทดสอบ สาขาทดลอง"
