"""เทส app/receipt_check/duplicate_check.py — ด่านกันแต้มซ้ำ

★ ทุกเคสในไฟล์นี้มาจากใบเสร็จจริงในชุดทดสอบ 28 รูป ไม่ได้คิดขึ้นเอง
  (ดู tests/fixtures/expected/README.md — หัวข้อ "เคสกับดัก")

เทสสองด้านที่ตรงข้ามกันเสมอ:
    ต้องจับได้     — ใบซ้ำหลุด = ให้แต้มสองเท่า (ร้ายแรงที่สุด)
    ต้องไม่จับเกิน — ใบที่ไม่ซ้ำโดนบล็อก = ลูกค้าเสียแต้มที่ควรได้
"""
from datetime import date, time

import pytest

from app.database.members import Member
from app.database.receipts import STATUS_AWARDED, STATUS_FAILED, ReceiptRecord
from app.database.tenants import Tenant
from app.receipt_check.duplicate_check import find_duplicate
from app.receipt_data.receipt_schema import Receipt

TENANT = "v-club"
OTHER_TENANT = "other-brand"


@pytest.fixture
def member_id(db_session) -> int:
    db_session.add(Tenant(id=TENANT, name="V-CLUB"))
    member = Member(tenant_id=TENANT, line_user_id="U1", crm_customer_id="C1")
    db_session.add(member)
    db_session.commit()
    return member.id


@pytest.fixture
def other_member_id(db_session, member_id) -> int:
    other = Member(tenant_id=TENANT, line_user_id="U2", crm_customer_id="C2")
    db_session.add(other)
    db_session.commit()
    return other.id


def _receipt(**overrides) -> Receipt:
    fields = dict(
        tenant_id=TENANT,
        merchant="ร้านทดสอบ",
        merchant_code=None,
        receipt_no=None,
        receipt_date=date(2026, 6, 6),
        receipt_time=time(17, 13),
        reference_codes=[],
        total_amount=79.0,
        source_image_id="img-1",
    )
    fields.update(overrides)
    return Receipt(**fields)


def _store(session, receipt: Receipt, *, member_id: int, status: str = STATUS_AWARDED):
    record = ReceiptRecord(
        tenant_id=receipt.tenant_id,
        member_id=member_id,
        content_fingerprint=f"fp-{receipt.source_image_id}",
        image_fingerprint=f"img-{receipt.source_image_id}",
        merchant=receipt.merchant,
        merchant_code=receipt.merchant_code,
        receipt_no=receipt.receipt_no,
        receipt_date=receipt.receipt_date,
        receipt_time=receipt.receipt_time,
        total_amount=receipt.total_amount,
        reference_codes=receipt.reference_codes,
        status=status,
        source_image_id=receipt.source_image_id,
    )
    session.add(record)
    session.commit()
    return record


# ═══════════════════════════════════════════
# ต้องจับได้ — ไม่งั้นให้แต้มซ้ำ
# ═══════════════════════════════════════════

def test_shared_reference_code_is_duplicate(db_session, member_id):
    """★ เคสจริง: ใบ KFC 149 ถ่ายสองมุม ทั้งคู่อ่าน Invoice ID ได้ตรงกัน"""
    _store(db_session, _receipt(reference_codes=["12102-002-0044557"], total_amount=149.0),
           member_id=member_id)

    verdict = find_duplicate(
        db_session,
        _receipt(reference_codes=["12102-002-0044557"], total_amount=149.0, source_image_id="img-2"),
        member_id=member_id,
    )
    assert verdict.is_duplicate


def test_receipt_and_card_slip_of_same_purchase_is_duplicate(db_session, member_id):
    """★ เคสจริง: KFC 149 มีทั้งใบเสร็จ (18:15) และสลิปบัตร (18:15:08)

    เลขอ้างอิงของสองใบไม่ตรงกันสักตัว (Invoice ID กับ TRANS ID คนละระบบ)
    แต่เป็นการซื้อครั้งเดียว ต้องได้แต้มครั้งเดียว → ต้องอาศัย ยอด+วันที่+เวลา
    """
    _store(db_session, _receipt(
        reference_codes=["12102-002-0044557"], total_amount=149.0, receipt_time=time(18, 15),
    ), member_id=member_id)

    verdict = find_duplicate(db_session, _receipt(
        reference_codes=["003646657141"], total_amount=149.0, receipt_time=time(18, 15, 8),
        source_image_id="img-2",
    ), member_id=member_id)
    assert verdict.is_duplicate


def test_duplicate_when_reference_unreadable_on_one_photo(db_session, member_id):
    """★ เคสจริง: ใบ DQ 79 บาท รูปหนึ่งหัวใบหลุดเฟรมจนไม่มีเลขใบกำกับเลย

    รูปที่อ่านเลขไม่ได้ต้องยังถูกจับว่าซ้ำ ไม่ใช่หลุดผ่านเพราะ "ไม่มีเลขให้เทียบ"
    """
    _store(db_session, _receipt(reference_codes=["23191"]), member_id=member_id)

    verdict = find_duplicate(
        db_session, _receipt(reference_codes=[], source_image_id="img-2"), member_id=member_id
    )
    assert verdict.is_duplicate


def test_duplicate_when_date_misread_by_one_day(db_session, member_id):
    """★ เคสจริง (#13): ใบ DQ วันที่ 06/06/2026 ถูก OCR อ่านเป็น 05/05/2026

    ถ้าเชื่อวันที่แบบตรงเป๊ะ ใบซ้ำที่อ่านวันเพี้ยนจะหลุดผ่านไปได้แต้มสองเท่า
    """
    _store(db_session, _receipt(receipt_date=date(2026, 6, 6)), member_id=member_id)

    verdict = find_duplicate(
        db_session,
        _receipt(receipt_date=date(2026, 6, 5), source_image_id="img-2"),
        member_id=member_id,
    )
    assert verdict.is_duplicate


def test_duplicate_when_time_unreadable(db_session, member_id):
    """อ่านเวลาไม่ได้ = ไม่รู้ → ต้องไม่กลายเป็นเหตุผลให้ปล่อยผ่าน"""
    _store(db_session, _receipt(receipt_time=time(17, 13)), member_id=member_id)

    verdict = find_duplicate(
        db_session, _receipt(receipt_time=None, source_image_id="img-2"), member_id=member_id
    )
    assert verdict.is_duplicate


def test_shared_reference_blocks_across_members(db_session, member_id, other_member_id):
    """กระดาษ 1 ใบต้องแลกแต้มได้ครั้งเดียว ไม่ว่าใครเป็นคนส่ง

    กันเคสส่งต่อรูปใบเสร็จให้เพื่อนแล้วได้แต้มอีกรอบ
    """
    _store(db_session, _receipt(reference_codes=["23191"]), member_id=member_id)

    verdict = find_duplicate(
        db_session,
        _receipt(reference_codes=["23191"], source_image_id="img-2"),
        member_id=other_member_id,
    )
    assert verdict.is_duplicate


# ═══════════════════════════════════════════
# ต้องไม่จับเกิน — ไม่งั้นลูกค้าเสียแต้มที่ควรได้
# ═══════════════════════════════════════════

def test_same_shop_same_day_same_amount_but_38_minutes_apart_is_not_duplicate(
    db_session, member_id
):
    """★★ เคสกับดักที่สำคัญที่สุดในชุดทดสอบ

    ลูกค้าซื้อไอศกรีม DQ 79 บาท สองครั้งในวันเดียวกัน ห่างกัน 38 นาที
        17:13  ใบกำกับ 23191  CONE(L) + BZ OVL MINT CHIP
        17:51  ใบกำกับ 23222  BG BZ FERRERO S
    ร้านเดียวกัน วันเดียวกัน ยอดเท่ากันเป๊ะ — แยกได้ด้วย "เวลา" เท่านั้น
    ถ้าเทสนี้แดง แปลว่าลูกค้าที่ซื้อซ้ำจะไม่ได้แต้มครั้งที่สอง
    """
    _store(db_session, _receipt(reference_codes=["23191"], receipt_time=time(17, 13)),
           member_id=member_id)

    verdict = find_duplicate(db_session, _receipt(
        reference_codes=["23222"], receipt_time=time(17, 51), source_image_id="img-2",
    ), member_id=member_id)
    assert not verdict.is_duplicate


def test_different_known_shop_is_not_duplicate(db_session, member_id):
    """★ ซื้อของราคาเท่ากันจากคนละร้าน เวลาใกล้กัน = คนละใบแน่นอน

    เกิดได้จริงในห้าง: ซื้อของ 79 บาทที่ร้านหนึ่ง แล้วเดินไปอีกร้านซื้ออีก 79 บาท
    ถ้าไม่มีกฎนี้ ใบที่สองจะถูกบล็อกเพราะ ยอด+วัน+เวลา ใกล้กันหมด
    """
    _store(db_session, _receipt(merchant_code="kfc"), member_id=member_id)

    verdict = find_duplicate(
        db_session,
        _receipt(merchant_code="dq", source_image_id="img-2"),
        member_id=member_id,
    )
    assert not verdict.is_duplicate


def test_unknown_shop_on_one_photo_does_not_release_a_duplicate(db_session, member_id):
    """★ รู้จักร้านแค่ใบเดียว = "ไม่รู้" ต้องไม่กลายเป็นเหตุผลให้ปล่อยผ่าน

    รูปคนละมุมของใบเดียวกันอาจอ่านร้านได้แค่รูปเดียว (วัดจริง: 27/28 ไม่ใช่ 28/28)
    ถ้าตัดสินว่า "คนละร้าน" ตรงนั้น ใบซ้ำจะหลุด = ให้แต้มสองเท่า
    """
    _store(db_session, _receipt(merchant_code="kfc"), member_id=member_id)

    verdict = find_duplicate(
        db_session,
        _receipt(merchant_code=None, source_image_id="img-2"),
        member_id=member_id,
    )
    assert verdict.is_duplicate


def test_different_amount_is_not_duplicate(db_session, member_id):
    _store(db_session, _receipt(total_amount=79.0), member_id=member_id)

    verdict = find_duplicate(
        db_session, _receipt(total_amount=39.0, source_image_id="img-2"), member_id=member_id
    )
    assert not verdict.is_duplicate


def test_different_day_is_not_duplicate(db_session, member_id):
    """ซื้อของราคาเท่ากันคนละวัน = คนละใบ (ห่างเกินที่ OCR จะอ่านพลาดได้)"""
    _store(db_session, _receipt(receipt_date=date(2026, 6, 6)), member_id=member_id)

    verdict = find_duplicate(
        db_session,
        _receipt(receipt_date=date(2026, 6, 10), source_image_id="img-2"),
        member_id=member_id,
    )
    assert not verdict.is_duplicate


def test_weak_signals_do_not_block_another_member(db_session, member_id, other_member_id):
    """คนละคนซื้อของราคาเท่ากันเวลาใกล้กัน เป็นเรื่องปกติในร้านอาหารช่วงพีค

    ถ้าไม่จำกัดขอบเขต ลูกค้าคนที่สองจะถูกปฏิเสธเพราะคนแรกส่งมาก่อน
    """
    _store(db_session, _receipt(), member_id=member_id)

    verdict = find_duplicate(
        db_session, _receipt(source_image_id="img-2"), member_id=other_member_id
    )
    assert not verdict.is_duplicate


def test_other_tenant_receipt_is_not_duplicate(db_session, member_id):
    """คนละแบรนด์ต้องไม่เห็นประวัติของกันและกัน"""
    _store(db_session, _receipt(reference_codes=["23191"]), member_id=member_id)

    verdict = find_duplicate(
        db_session,
        _receipt(tenant_id=OTHER_TENANT, reference_codes=["23191"], source_image_id="img-2"),
        member_id=member_id,
    )
    assert not verdict.is_duplicate


# ═══════════════════════════════════════════
# แถวที่ยังไม่ได้แต้ม ต้องไม่บล็อกลูกค้าถาวร
# ═══════════════════════════════════════════

def test_failed_row_is_returned_so_caller_can_retry(db_session, member_id):
    """CRM ล่มตอนส่งแต้ม → แถวเป็น FAILED · ลูกค้าส่งใหม่ต้อง "ใช้แถวเดิม" ไม่ใช่โดนบล็อก

    ผู้เรียก (scan_job) ดูจาก verdict.existing.status เพื่อแยกสองกรณีนี้
    ถ้า find_duplicate ไม่คืนแถวมาด้วย ลูกค้าจะไม่มีวันได้แต้มของใบนี้เลย
    """
    stored = _store(db_session, _receipt(reference_codes=["23191"]),
                    member_id=member_id, status=STATUS_FAILED)

    verdict = find_duplicate(
        db_session,
        _receipt(reference_codes=["23191"], source_image_id="img-2"),
        member_id=member_id,
    )
    assert verdict.is_duplicate
    assert verdict.existing is not None
    assert verdict.existing.id == stored.id
    assert verdict.existing.status == STATUS_FAILED


def test_awarded_row_wins_over_failed_row(db_session, member_id):
    """★ ถ้าตรงกับหลายแถว แถวที่ได้แต้มไปแล้วต้องชนะ

    ไม่งั้นระบบจะเลือกแถว FAILED แล้ว "ส่งซ้ำ" ทั้งที่แต้มออกไปแล้ว = ให้แต้มสองเท่า
    """
    _store(db_session, _receipt(reference_codes=["23191"]),
           member_id=member_id, status=STATUS_FAILED)
    awarded = _store(db_session, _receipt(reference_codes=["23191"], source_image_id="img-2"),
                     member_id=member_id, status=STATUS_AWARDED)

    verdict = find_duplicate(
        db_session,
        _receipt(reference_codes=["23191"], source_image_id="img-3"),
        member_id=member_id,
    )
    assert verdict.existing is not None
    assert verdict.existing.id == awarded.id


def test_verdict_always_carries_a_reason(db_session, member_id):
    """เหตุผลต้องมีเสมอ — แอดมินต้องตอบลูกค้าได้ว่าทำไมใบนี้ถูกปฏิเสธ"""
    _store(db_session, _receipt(reference_codes=["23191"]), member_id=member_id)

    duplicate = find_duplicate(
        db_session, _receipt(reference_codes=["23191"], source_image_id="img-2"),
        member_id=member_id,
    )
    unique = find_duplicate(
        db_session, _receipt(total_amount=1.0, source_image_id="img-3"), member_id=member_id
    )
    assert duplicate.reason
    assert unique.reason
