"""เทส app/receipt_data/receipt_identity.py

★ นี่คือส่วนหนึ่งของกลไกกัน "แต้มซ้ำ" — ความเสียหายที่แก้ยากที่สุด
เทสจึงเน้น 2 ด้านที่ตรงข้ามกัน: ใบเดียวกันต้องได้ค่าเดียวกัน · คนละใบต้องได้คนละค่า

⚠ ลายนิ้วมือไม่ใช่ "ตัวตัดสิน" ว่าใบซ้ำ (ตัวตัดสินคือ duplicate_check ซึ่งเทียบหลายสัญญาณ)
  ที่นี่เทสแค่ว่าค่าที่คำนวณออกมา "เสถียร" และ "แยกของที่ควรแยก" ได้
"""
from datetime import date

from app.receipt_data.receipt_identity import content_fingerprint, image_fingerprint

TENANT = "v-club"
IMAGE = b"pretend-jpeg-bytes"


def _fp(**overrides) -> str:
    fields = dict(
        reference_codes=["INV-001"],
        receipt_no=None,
        receipt_date=date(2026, 8, 1),
        total_amount=250.0,
    )
    fields.update(overrides)
    return content_fingerprint(TENANT, **fields)


# ═══════════════════════════════════════════
# image_fingerprint — จับไฟล์เดียวกันเป๊ะ
# ═══════════════════════════════════════════

def test_same_image_same_fingerprint():
    assert image_fingerprint(TENANT, IMAGE) == image_fingerprint(TENANT, IMAGE)


def test_different_image_different_fingerprint():
    assert image_fingerprint(TENANT, IMAGE) != image_fingerprint(TENANT, IMAGE + b"x")


def test_same_image_different_tenant_differs():
    """คนละแบรนด์ต้องไม่ชนกัน แม้เป็นไฟล์เดียวกันเป๊ะ"""
    assert image_fingerprint("v-club", IMAGE) != image_fingerprint("other", IMAGE)


# ═══════════════════════════════════════════
# content_fingerprint — จับ "ใบเดียวกัน" แม้ถ่ายคนละรูป
# ═══════════════════════════════════════════

def test_same_receipt_content_same_fingerprint():
    """ถ่ายใบเดิมใหม่ = พิกเซลคนละชุด แต่เนื้อหาเดียวกัน → ต้องได้ค่าเดียวกัน"""
    assert _fp() == _fp()


def test_amount_formatting_does_not_matter():
    """250 กับ 250.00 คือยอดเดียวกัน ต้องไม่กลายเป็นคนละใบ"""
    assert _fp(total_amount=250) == _fp(total_amount=250.00)


def test_different_amount_is_different_receipt():
    assert _fp(total_amount=250.0) != _fp(total_amount=251.0)


def test_different_reference_code_is_different_receipt():
    assert _fp(reference_codes=["INV-001"]) != _fp(reference_codes=["INV-002"])


def test_different_date_is_different_receipt():
    assert _fp(receipt_date=date(2026, 8, 1)) != _fp(receipt_date=date(2026, 8, 2))


def test_different_tenant_is_different_receipt():
    """คนละแบรนด์ต้องไม่ชนกัน แม้ใบเสร็จเหมือนกันทุกอย่าง"""
    assert content_fingerprint(
        "v-club", reference_codes=["A1"], receipt_no=None,
        receipt_date=date(2026, 8, 1), total_amount=100.0,
    ) != content_fingerprint(
        "other", reference_codes=["A1"], receipt_no=None,
        receipt_date=date(2026, 8, 1), total_amount=100.0,
    )


# ═══════════════════════════════════════════
# ★ กฎที่มาจากการวัดกับใบเสร็จจริง 28 รูป — อย่าลบ
# ═══════════════════════════════════════════

def test_extra_reference_code_does_not_change_fingerprint():
    """★ รูปคนละมุมของใบเดียวกัน อ่านเลขอ้างอิงได้ "ไม่ครบเท่ากัน"

    วัดจริง: สลิป KFC 149 บาท รูปหนึ่งอ่านได้ 4 เลข อีกรูปอ่านได้ 5 เลข
    ถ้าแฮชทั้งชุด ค่าจะเพี้ยนทันที → ใบเดียวกันกลายเป็นคนละใบ → ได้แต้มสองเท่า
    จึงใช้เฉพาะ "เลขที่น้อยที่สุดเมื่อเรียง" ซึ่งตรงกันทั้งสองรูป
    """
    few = ["003646657141", "071055", "071650"]
    many = ["003646657141", "071055", "071650", "922535"]
    assert _fp(reference_codes=few) == _fp(reference_codes=many)


def test_reference_code_order_does_not_matter():
    """OCR คืนบรรทัดมาคนละลำดับได้ ลำดับต้องไม่ทำให้กลายเป็นคนละใบ"""
    assert _fp(reference_codes=["b1111", "a2222"]) == _fp(reference_codes=["a2222", "b1111"])


def test_merchant_is_not_part_of_identity():
    """★ ชื่อร้านต้องไม่มีผลต่อลายนิ้วมือ

    เหตุผล (วัดจริง): ใบ KFC 149 ใบเดียวกัน สองรูปอ่านชื่อร้านได้คนละเรื่อง
        รูปหนึ่ง "CRG-KFC 12IO2 (KEC-BIO C NAKORNSAVAN)"
        อีกรูป  "2330 Host: Prapapan #2330 BOX AI1 Easy"
    เวอร์ชันแรกใส่ชื่อร้านในลายนิ้วมือ ทำให้ใบเดียวกันได้คนละค่า = ได้แต้มสองเท่า
    เทสนี้พิสูจน์ว่าฟังก์ชันไม่รับชื่อร้านเข้ามาเลย (ไม่ใช่แค่ "บังเอิญไม่ใช้")
    """
    import inspect

    assert "merchant" not in inspect.signature(content_fingerprint).parameters


def test_receipt_no_used_when_no_reference_code():
    """ใบเสร็จที่อ่านเลขอ้างอิงไม่ได้ ยังต้องใช้เลขที่ใบเสร็จแยกใบได้"""
    assert _fp(reference_codes=[], receipt_no="A1") != _fp(reference_codes=[], receipt_no="A2")


def test_no_identity_at_all_still_computes():
    """อ่านอะไรไม่ได้เลยก็ต้องคำนวณได้ (อาศัยวันที่+ยอด) — duplicate_check เป็นตัวตัดสินแทน"""
    assert _fp(reference_codes=[], receipt_no=None) == _fp(reference_codes=[], receipt_no=None)


def test_fingerprint_is_url_safe_and_short():
    """ค่านี้เคยถูกส่งเป็น reference ใน query string ของ CRM — ต้องไม่มีอักขระแปลก"""
    fingerprint = _fp()
    assert fingerprint.isalnum()
    assert len(fingerprint) == 32
