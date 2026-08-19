"""เทส app/receipt_data/receipt_identity.py

★ นี่คือกลไกกัน "แต้มซ้ำ" — ความเสียหายที่แก้ยากที่สุด (แต้มออกไปแล้วดึงคืนยาก)
เทสจึงเน้น 2 ด้านที่ตรงข้ามกัน: ใบเดียวกันต้องได้ค่าเดียวกัน · คนละใบต้องได้คนละค่า
"""
from datetime import date

from app.receipt_data.receipt_identity import image_fingerprint, receipt_fingerprint

TENANT = "v-club"
IMAGE = b"pretend-jpeg-bytes"


def _fp(**overrides) -> str:
    fields = dict(
        merchant="ร้านทดสอบ",
        receipt_no="INV-001",
        receipt_date=date(2026, 8, 1),
        total_amount=250.0,
    )
    fields.update(overrides)
    return receipt_fingerprint(TENANT, **fields)


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
# receipt_fingerprint — จับ "ใบเดียวกัน" แม้ถ่ายคนละรูป
# ═══════════════════════════════════════════

def test_same_receipt_content_same_fingerprint():
    """ถ่ายใบเดิมใหม่ = พิกเซลคนละชุด แต่เนื้อหาเดียวกัน → ต้องได้ค่าเดียวกัน
    (นี่คือเหตุผลที่ต้องมี fingerprint ระดับเนื้อหา ไม่ใช่แค่ระดับไฟล์)"""
    assert _fp() == _fp()


def test_amount_formatting_does_not_matter():
    """250 กับ 250.00 คือยอดเดียวกัน ต้องไม่กลายเป็นคนละใบ"""
    assert _fp(total_amount=250) == _fp(total_amount=250.00)


def test_merchant_case_and_space_do_not_matter():
    """OCR อ่านชื่อร้านได้ตัวพิมพ์/ช่องว่างต่างกันเล็กน้อย ไม่ควรนับเป็นคนละใบ"""
    assert receipt_fingerprint(
        TENANT, merchant="  Test Shop  ", receipt_no="A1",
        receipt_date=date(2026, 8, 1), total_amount=100.0,
    ) == receipt_fingerprint(
        TENANT, merchant="test shop", receipt_no="a1",
        receipt_date=date(2026, 8, 1), total_amount=100.0,
    )


def test_different_amount_is_different_receipt():
    assert _fp(total_amount=250.0) != _fp(total_amount=251.0)


def test_different_receipt_no_is_different_receipt():
    assert _fp(receipt_no="INV-001") != _fp(receipt_no="INV-002")


def test_different_date_is_different_receipt():
    assert _fp(receipt_date=date(2026, 8, 1)) != _fp(receipt_date=date(2026, 8, 2))


def test_different_merchant_is_different_receipt():
    assert _fp(merchant="ร้าน ก") != _fp(merchant="ร้าน ข")


def test_missing_receipt_no_still_works():
    """ใบเสร็จบางร้านไม่มีเลขที่ — ต้องยังคำนวณได้ (อาศัย ร้าน+วันที่+ยอด)"""
    assert _fp(receipt_no=None) == _fp(receipt_no=None)
    assert _fp(receipt_no=None) != _fp(receipt_no="INV-001")


def test_fingerprint_is_url_safe_and_short():
    """ค่านี้ถูกส่งเป็น reference ใน query string ของ CRM — ต้องไม่มีอักขระแปลก"""
    fingerprint = _fp()
    assert fingerprint.isalnum()
    assert len(fingerprint) == 32
