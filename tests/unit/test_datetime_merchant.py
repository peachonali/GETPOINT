"""เทส datetime_parser + merchant_name

★ ทุกเคสมาจากใบเสร็จจริง 28 ใบที่เก็บมา — ชื่อเทสบอกด้วยว่าเจอจากใบไหน
  เพื่อให้คนแก้ทีหลังรู้ว่ากฎแต่ละข้อมีไว้กันอะไร
"""
from datetime import date, time

from app.receipt_data.datetime_parser import find_date, find_time
from app.receipt_data.merchant_name import find_merchant

TODAY = date(2026, 8, 21)


# ═══════════════════════════════════════════
# วันที่
# ═══════════════════════════════════════════

def test_month_name_format():
    """สลิปธนาคารกรุงเทพใช้ 'Jun 6, 2026'"""
    assert find_date(["Jun 6, 2026"], today=TODAY) == date(2026, 6, 6)


def test_numeric_format():
    assert find_date(["Host: Prapapan 06/06/2026"], today=TODAY) == date(2026, 6, 6)


def test_buddhist_year_converted():
    """ใบเสร็จไทยพิมพ์ปี พ.ศ. — ต้องแปลงเป็น ค.ศ. ไม่งั้นคลาด 543 ปี"""
    assert find_date(["06/06/2569 13:42"], today=TODAY) == date(2026, 6, 6)


def test_implausible_year_rejected():
    """★ เจอจริง: ระบบเคยอ่าน 'SFSL 120-9 (VAT) (1-01/69)' จากข้อความแนวตั้ง
    ข้างสลิป มาเป็นวันที่ปี 2069 — ใบเสร็จจากอนาคต 43 ปีต้องถูกปฏิเสธ"""
    assert find_date(["SFSL 120-9 (VAT) (1-01/69)"], today=TODAY) is None


def test_month_name_wins_over_stray_numbers():
    """ชื่อเดือนเดาผิดยากกว่าตัวเลขล้วน → ต้องชนะแม้อยู่บรรทัดล่างกว่า"""
    lines = ["TID#47853174 01/72", "Jun 6, 2026"]
    assert find_date(lines, today=TODAY) == date(2026, 6, 6)


def test_no_date_returns_none():
    assert find_date(["ขอบคุณที่ใช้บริการ"], today=TODAY) is None


# ═══════════════════════════════════════════
# เวลา
# ═══════════════════════════════════════════

def test_time_with_colons():
    assert find_time(["Time:17:51:18"]) == time(17, 51, 18)


def test_pm_misread_as_ph_still_works():
    """★ KFC: OCR อ่าน '5:25 PM' เป็น '5:25 PH' บนกระดาษความร้อน
    ถ้าไม่รับ จะได้ 05:25 แทน 17:25 — คลาด 12 ชั่วโมง"""
    assert find_time(["Host: Prapapan 06/06/2026", "5:25 PH"]) == time(17, 25)


def test_compact_time_next_to_date():
    """★ สลิปธนาคาร: 'Jun 6, 2026 181508' — ทวิภาคหายหมด"""
    assert find_time(["Jun 6, 2026 181508"]) == time(18, 15, 8)


def test_six_digit_code_is_not_time():
    """★ เลข 6 หลักบนใบเสร็จส่วนใหญ่เป็นรหัส ไม่ใช่เวลา
    รับเฉพาะตอนอยู่บรรทัดเดียวกับวันที่เท่านั้น"""
    assert find_time(["STAN#071650", "BATCH#000314"]) is None


# ═══════════════════════════════════════════
# ชื่อร้าน
# ═══════════════════════════════════════════

def test_skips_document_heading():
    """Dairy Queen: บรรทัดแรกคือ 'TAX INVOICE (ABB) : 23191' ไม่ใช่ชื่อร้าน"""
    lines = ["TAX INVOICE (ABB) : 23191", "MINOR DQ LIMITED", "DQ_BIG C NAKHONSAWAN"]
    merchant = find_merchant(lines)
    assert merchant and "MINOR DQ" in merchant


def test_skips_bank_name_on_card_slip():
    """★ สลิปบัตร: 'Bangkok Bank' คือธนาคารผู้รับชำระ ร้านจริงคือ KFC"""
    lines = ["Bangkok Bank", "KFC", "KFC-12102", "BIG C NAKORNSAWAN"]
    assert find_merchant(lines) == "KFC KFC-12102"


def test_skips_garbled_thai_bank_name():
    """★ เจอจริง: 'ธนาคารกรุงเทพ' ถูกอ่านเป็น 'ธนาตารกรุวเทน'
    ถ้าจับไม่ได้ ระบบจะเอาชื่อธนาคารไปเป็นชื่อร้าน"""
    lines = ["ธนาตารกรุวเทน", "KFC", "BIG C NAKORNSAWAN"]
    merchant = find_merchant(lines)
    assert merchant and "ธนา" not in merchant


def test_skips_url_line():
    lines = ["www.talktoDQthailand.com", "MINOR DQ LIMITED"]
    merchant = find_merchant(lines)
    assert merchant and "www" not in merchant


def test_price_line_is_not_a_merchant():
    """บรรทัดที่มีราคาคือรายการสินค้า ไม่ใช่ชื่อร้าน"""
    lines = ["ร้านทดสอบ สาขาทดลอง", "รวมทั้งสิ้น 100.00"]
    assert find_merchant(lines) == "ร้านทดสอบ สาขาทดลอง"


def test_returns_none_when_nothing_looks_like_a_name():
    assert find_merchant(["12345", "***", "TAX ID: 0105532021090"]) is None
