"""★ ตัดสินว่า "ใบนี้เคยได้แต้มไปแล้วหรือยัง"

นี่คือกลไกที่กันความเสียหายที่แก้ยากที่สุด: **ให้แต้มซ้ำ**
แต้มที่ให้ผิดไปแล้วดึงคืนยาก และไม่มีใครรู้ตัว — ทั้งลูกค้าและระบบ

═══════════════════════════════════════════════════════════════
ทำไมเทียบด้วย "แฮชค่าเดียว" ไม่พอ (พิสูจน์ด้วยใบเสร็จจริง 28 รูป)
═══════════════════════════════════════════════════════════════

รูป 28 ใบคือ **การซื้อ 12 ครั้ง · กระดาษ 14 ใบ · ถ่ายใบละ 2 มุม**
เอามาวัดแล้วเจอสามเรื่องที่แฮชเดียวแก้ไม่ได้:

1. **รูปคนละมุมของใบเดียวกัน OCR อ่านได้ไม่เท่ากัน**
   ใบ DQ 79 บาท: รูปหนึ่งอ่านเลขใบกำกับ "23191" ได้ อีกรูปหัวใบหลุดเฟรมจนไม่มีเลขเลย
   → แฮชคนละค่า ทั้งที่เป็นกระดาษใบเดียวกัน

2. **การซื้อครั้งเดียวมีกระดาษ 2 ใบ** (ใบเสร็จร้าน + สลิปบัตร)
   KFC 149: ใบเสร็จมี "Invoice ID 12102-002-0044557" สลิปมี "TRANS ID 003646657141"
   → เลขอ้างอิงไม่ตรงกันสักตัว แต่ต้องได้แต้มครั้งเดียว
   สิ่งที่ตรงกันคือ ยอด + วันที่ + **เวลา (ห่างกัน 8 วินาที)**

3. **คนละใบจริงๆ ที่เหมือนกันแทบทุกอย่าง**
   DQ 79 บาท 2 ใบ: ร้านเดียวกัน วันเดียวกัน ยอดเท่ากันเป๊ะ ห่างกัน 38 นาที
   → ถ้าตัดสินว่าซ้ำ ลูกค้าเสียแต้มที่ควรได้
   สิ่งที่แยกได้มีแค่ **เลขใบกำกับ · เวลา · ชื่อรายการสินค้า**

จึงต้องเทียบ "ทีละใบที่เคยรับไว้" ด้วยหลายสัญญาณ ไม่ใช่เทียบแฮชค่าเดียว

═══════════════════════════════════════════════════════════════
ทิศทางของความผิดพลาด (หลักที่ยึดตลอด)
═══════════════════════════════════════════════════════════════
    ปล่อยใบซ้ำผ่าน  = ให้แต้มสองเท่า · ไม่มีใครรู้ตัว · แก้ยาก   ← ยอมไม่ได้
    จับซ้ำเกินจริง  = ลูกค้าไม่ได้แต้ม · ลูกค้าทักท้วง · แอดมินแก้ให้ได้

→ เมื่อไม่มั่นใจ ให้ตอบว่า "ซ้ำ" (บล็อกไว้ก่อน)
  ทางหนีมีเฉพาะกรณีที่ **มั่นใจสูงว่าคนละใบ** เท่านั้น
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.receipts import STATUS_AWARDED, STATUS_REJECTED, ReceiptRecord
from app.receipt_data.receipt_schema import Receipt

#: ยอดต่างกันไม่เกินนี้ถือว่าเท่ากัน (ปัดเศษสตางค์)
_AMOUNT_TOLERANCE = 0.01

#: ★ ห่างกันเกินเท่านี้ในวันเดียวกัน = คนละการซื้อแน่นอน
#:
#: เลือก 15 นาทีจากของจริงสองด้าน:
#:   ต้องมากกว่า  ~1 นาที  — ใบเสร็จกับสลิปบัตรของการซื้อเดียวกันห่างกัน 8-14 วินาที
#:   ต้องน้อยกว่า 38 นาที  — DQ 79 บาทสองใบที่เป็นคนละการซื้อจริง ห่างกัน 38 นาที
#: 15 นาทีอยู่กลางๆ และเผื่อร้านที่พิมพ์ใบเสร็จตอนสั่งแต่รูดบัตรตอนรับของ
_DIFFERENT_PURCHASE_MINUTES = 15

#: ★ วันที่ต่างกันเกินกี่วันถึงจะเชื่อว่าเป็นคนละใบ
#:
#: ไม่ใช้ "ต่างกัน 1 วันก็คนละใบ" เพราะ OCR อ่านวันที่ผิดได้จริง
#: เจอจริง (#13): ใบ DQ วันที่ 06/06/2026 ถูกอ่านเป็น 05/05/2026
#: ถ้าเชื่อวันที่แบบตรงเป๊ะ ใบซ้ำที่อ่านวันเพี้ยนจะหลุดผ่านไปได้แต้มสองเท่า
_DATE_TOLERANCE_DAYS = 1


@dataclass(frozen=True)
class DuplicateVerdict:
    """ผลการตรวจ — เก็บ "เพราะอะไร" ไว้ด้วยเสมอ เพื่อให้ตอบลูกค้า/แอดมินได้ว่าทำไมถูกปฏิเสธ"""

    is_duplicate: bool
    reason: str
    existing: ReceiptRecord | None = None

    @classmethod
    def unique(cls) -> DuplicateVerdict:
        return cls(is_duplicate=False, reason="ไม่พบใบที่ตรงกันในประวัติ")


def find_duplicate(session: Session, receipt: Receipt, *, member_id: int) -> DuplicateVerdict:
    """หาว่าใบเสร็จใบนี้เคยถูกบันทึกไปแล้วหรือยัง

    ค้นเฉพาะแถวที่ "ยอดเท่ากัน" ก่อนเสมอ — ยอดเงินคือ field ที่ OCR อ่านแม่นที่สุด
    (วัดจริง: ถูก 96% ผิด 0%) และมันตัดผู้สมัครทิ้งได้เกือบหมดในคิวรีเดียว

    ★ เมื่อตรงกับหลายแถว ให้ "แถวที่ได้แต้มไปแล้ว" ชนะเสมอ
      เพราะผู้เรียกใช้ผลตรงนี้ตัดสินสองเรื่องที่ต่างกัน: ได้แต้มแล้ว = ปฏิเสธ ·
      ยังไม่ได้แต้ม = ส่งซ้ำให้ได้ · ถ้าคืนแถวที่ยังไม่ได้แต้มทั้งที่มีแถวที่ได้แล้วอยู่
      ระบบจะให้แต้มซ้ำ ซึ่งคือสิ่งที่ไฟล์นี้มีไว้ป้องกัน
    """
    matches = [
        verdict
        for stored in _candidates(session, receipt)
        if (verdict := _compare(receipt, stored, member_id=member_id)).is_duplicate
    ]
    if not matches:
        return DuplicateVerdict.unique()

    awarded = [m for m in matches if m.existing is not None and m.existing.status == STATUS_AWARDED]
    return awarded[0] if awarded else matches[0]


def _candidates(session: Session, receipt: Receipt) -> list[ReceiptRecord]:
    """แถวที่ยอดเท่ากันในแบรนด์เดียวกัน — ผู้สมัครทั้งหมดที่ต้องเทียบ

    ★ ค้นทั้ง tenant ไม่จำกัดแค่สมาชิกคนเดียว โดยตั้งใจ
      เพราะกระดาษ 1 ใบต้องแลกแต้มได้ครั้งเดียว ไม่ว่าใครเป็นคนส่ง
      (ถ้าจำกัดแค่เจ้าของ ลูกค้าส่งต่อรูปใบเสร็จให้เพื่อนก็ได้แต้มอีกรอบ)
      แต่การตัดสินด้วยสัญญาณที่อ่อนกว่า จะจำกัดขอบเขตอีกชั้นใน _compare
    """
    low = receipt.total_amount - _AMOUNT_TOLERANCE
    high = receipt.total_amount + _AMOUNT_TOLERANCE
    statement = (
        select(ReceiptRecord)
        .where(ReceiptRecord.tenant_id == receipt.tenant_id)
        .where(ReceiptRecord.total_amount >= low)
        .where(ReceiptRecord.total_amount <= high)
        # แถวที่ถูกปฏิเสธไปแล้วไม่เคยได้แต้ม → ไม่ควรไปบล็อกใบอื่น
        .where(ReceiptRecord.status != STATUS_REJECTED)
        .order_by(ReceiptRecord.id)
    )
    return list(session.scalars(statement))


def _compare(receipt: Receipt, stored: ReceiptRecord, *, member_id: int) -> DuplicateVerdict:
    """เทียบใบใหม่กับใบที่เคยรับไว้ 1 ใบ — ตัดสินตามลำดับความมั่นใจจากสูงไปต่ำ"""

    # ── กฎ 1: แชร์เลขอ้างอิงอย่างน้อย 1 ตัว = กระดาษใบเดียวกันแน่นอน ──
    # เลขพวกนี้ (Invoice ID / TRANS ID / Tax INV) ไม่ซ้ำข้ามใบโดยธรรมชาติ
    # ใช้ข้ามสมาชิกได้ เพราะกระดาษใบเดียวแลกได้ครั้งเดียวไม่ว่าใครส่ง
    shared = _shared_reference(receipt, stored)
    if shared:
        return DuplicateVerdict(True, f"เลขอ้างอิงตรงกับใบที่เคยรับไว้ ({shared})", stored)

    # ── ตั้งแต่กฎ 2 ลงไปใช้สัญญาณที่อ่อนกว่า → จำกัดไว้แค่ "สมาชิกคนเดียวกัน" ──
    # คนละคนซื้อของราคาเท่ากันเวลาใกล้กันเป็นเรื่องปกติ (โดยเฉพาะร้านอาหารช่วงพีค)
    # ถ้าไม่จำกัด ลูกค้าคนที่สองจะถูกปฏิเสธเพราะคนแรกส่งมาก่อน
    if stored.member_id != member_id:
        return DuplicateVerdict(False, "คนละสมาชิก และไม่มีเลขอ้างอิงตรงกัน")

    # ── กฎ 2: คนละร้าน (และรู้จักร้านทั้งสองใบ) = คนละใบแน่นอน ──
    #
    # ★ ใช้ "รหัสร้าน" ไม่ใช่ "ชื่อร้าน" — ชื่อที่ OCR อ่านได้ไม่คงที่ระหว่างรูปของใบเดียวกัน
    #   ส่วนรหัสร้านมาจากเลขผู้เสียภาษีเป็นหลัก (วัดจริง 27/28 ถูก · ผิด 0)
    #
    # ★ ต้องรู้จักทั้งสองใบเท่านั้น — ถ้าใบใดใบหนึ่งอ่านร้านไม่ออก แปลว่า "ไม่รู้"
    #   ซึ่งต้องไม่กลายเป็นเหตุผลให้ปล่อยผ่าน (รูปคนละมุมของใบเดียวกันอาจอ่านร้าน
    #   ได้แค่รูปเดียว — ถ้าตัดสินว่าคนละใบตรงนั้น ใบซ้ำจะหลุด)
    if _merchants_clearly_differ(receipt.merchant_code, stored.merchant_code):
        return DuplicateVerdict(False, "คนละร้าน")

    # ── กฎ 3: วันที่ห่างกันเกินที่ OCR จะอ่านพลาดได้ = คนละใบ ──
    if _dates_clearly_differ(receipt.receipt_date, stored.receipt_date):
        return DuplicateVerdict(False, "วันที่บนใบเสร็จต่างกันชัดเจน")

    # ── กฎ 4: วันเดียวกัน แต่เวลาห่างกันเกินเกณฑ์ = คนละครั้ง ──
    gap = _minutes_apart(receipt.receipt_time, stored.receipt_time)
    if gap is not None and gap > _DIFFERENT_PURCHASE_MINUTES:
        return DuplicateVerdict(False, f"เวลาบนใบเสร็จห่างกัน {gap:.0f} นาที")

    # ── กฎ 5: เหลือแค่นี้แปลว่าแยกไม่ออก → ถือว่าซ้ำ (ฝั่งปลอดภัย) ──
    # ครอบคลุมทั้ง "ใบเดียวกันแต่อ่านเลขอ้างอิงไม่ได้" และ "ใบเสร็จคู่กับสลิปบัตร"
    return DuplicateVerdict(
        True, "ยอดเงิน วันที่ และเวลา ตรงกับใบที่เคยรับไว้ จนแยกไม่ออก", stored
    )


def _shared_reference(receipt: Receipt, stored: ReceiptRecord) -> str | None:
    stored_codes = {code.lower() for code in (stored.reference_codes or [])}
    for code in receipt.reference_codes:
        if code.lower() in stored_codes:
            return code
    return None


def _merchants_clearly_differ(left: str | None, right: str | None) -> bool:
    """รหัสร้านต่างกันจน "เชื่อได้ว่าเป็นคนละใบ" ไหม

    รู้จักร้านแค่ใบเดียว (หรือไม่รู้จักเลย) = ตอบว่า "ไม่ต่างชัดเจน"
    → ไปให้กฎถัดไปตัดสิน · การไม่รู้ต้องไม่กลายเป็นเหตุผลให้ปล่อยผ่าน
    """
    if left is None or right is None:
        return False
    return left != right


def _dates_clearly_differ(left: date | None, right: date | None) -> bool:
    """วันที่ต่างกันจน "เชื่อได้ว่าเป็นคนละใบ" ไหม

    อ่านไม่ได้ฝั่งใดฝั่งหนึ่ง = ตอบว่า "ไม่ต่างชัดเจน" → ไปให้กฎถัดไปตัดสิน
    (การไม่รู้ ต้องไม่กลายเป็นเหตุผลให้ปล่อยผ่าน)
    """
    if left is None or right is None:
        return False
    return abs((left - right).days) > _DATE_TOLERANCE_DAYS


def _minutes_apart(left: time | None, right: time | None) -> float | None:
    """เวลาสองค่าห่างกันกี่นาที · อ่านไม่ได้ฝั่งใดฝั่งหนึ่ง → None (ตัดสินด้วยกฎนี้ไม่ได้)

    ⚠ เทียบเฉพาะ "เวลาในหนึ่งวัน" ไม่ข้ามวัน เพราะกฎนี้ถูกเรียกหลังจากยืนยันแล้วว่า
      วันที่ไม่ต่างกันชัดเจน · 23:55 กับ 00:05 จะถูกมองว่าห่างกัน 23 ชั่วโมง 50 นาที
      ซึ่งทำให้ตอบว่า "คนละใบ" — ยอมรับได้เพราะเป็นฝั่งที่เสียหายน้อยกว่าเฉพาะเคสนี้
      (ใบเสร็จข้ามเที่ยงคืนพอดีมีน้อยมาก และวันที่จะต่างกันด้วยอยู่แล้ว)
    """
    if left is None or right is None:
        return None
    anchor = date(2000, 1, 1)
    delta = datetime.combine(anchor, left) - datetime.combine(anchor, right)
    return abs(delta.total_seconds()) / 60
