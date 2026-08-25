"""★ วัดว่าระบบ "กันใบซ้ำ" ได้จริงแค่ไหน — ตัวชี้วัดหลักของงานกันแต้มซ้ำ

วิธีใช้ (รันจาก backend/):
    python -m app.tools.measure_duplicate
    python -m app.tools.measure_duplicate --fresh    ← อ่าน OCR ใหม่ (ใช้เมื่อแก้โค้ด OCR)

วิธีวัด: ป้อนรูปทั้ง 28 ใบเข้าระบบ "ทีละใบตามลำดับ" ผ่าน duplicate_check ตัวจริง
บนฐานข้อมูลในหน่วยความจำ แล้วเทียบกับเฉลยว่า

    รูปแรกของการซื้อครั้งหนึ่ง  → ต้องผ่าน (ได้แต้ม)
    รูปที่สองของการซื้อเดิม     → ต้องถูกจับว่าซ้ำ

★ แยกผลเป็น 3 กอง เพราะราคาต่างกันคนละเรื่อง:
    จับได้      — ใบซ้ำถูกบล็อก (สิ่งที่ต้องการ)
    ★ หลุด     — ใบซ้ำได้แต้มอีกครั้ง (ร้ายแรงที่สุด · ไม่มีใครรู้ตัว)
    จับเกิน     — ใบที่ไม่ซ้ำถูกบล็อก (ลูกค้าเสียแต้ม · ลูกค้าทักท้วงได้ แอดมินแก้ได้)

เป้าหมาย: "หลุด = 0" มาก่อน "จับเกิน = 0" เสมอ
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.db import Base
from app.database.members import Member
from app.database.receipts import STATUS_AWARDED, ReceiptRecord
from app.database.tenants import Tenant
from app.receipt_check.duplicate_check import find_duplicate
from app.receipt_data.receipt_identity import content_fingerprint
from app.receipt_data.receipt_schema import Receipt
from app.tools.golden_set import Reading, load_truth, read_all

TENANT = "measure"


@dataclass
class Outcome:
    name: str
    purchase_id: str
    should_be_duplicate: bool
    was_duplicate: bool
    reason: str

    @property
    def missed(self) -> bool:
        """ควรถูกจับว่าซ้ำ แต่หลุดผ่าน = ให้แต้มซ้ำ"""
        return self.should_be_duplicate and not self.was_duplicate

    @property
    def over_blocked(self) -> bool:
        """ไม่ควรถูกจับ แต่โดนบล็อก = ลูกค้าเสียแต้ม"""
        return not self.should_be_duplicate and self.was_duplicate


def main(argv: list[str] | None = None) -> int:
    fresh = "--fresh" in (argv if argv is not None else sys.argv[1:])
    truth = load_truth()
    readings = read_all(fresh=fresh)

    with _fresh_database() as session:
        member_id = _seed_member(session)
        outcomes = [
            _feed_one(session, readings[name], truth[name], member_id=member_id)
            for name in sorted(readings, key=lambda n: _number(n))
            if readings[name].read_ok        # อ่านยอดไม่ได้ = ไม่เคยถึงด่านกันซ้ำอยู่แล้ว
        ]

    unreadable = [name for name, item in readings.items() if not item.read_ok]
    _report(outcomes, unreadable)
    # ออกด้วยรหัสผิดพลาดถ้ามีใบซ้ำหลุด — ใช้ต่อใน CI ได้
    return 1 if any(o.missed for o in outcomes) else 0


def _feed_one(session: Session, reading: Reading, truth: dict, *, member_id: int) -> Outcome:
    """ป้อนใบเสร็จ 1 ใบเข้าระบบเหมือนของจริง แล้วบันทึกว่าตัดสินอย่างไร"""
    receipt = _to_receipt(reading)
    purchase_id = truth["purchase_id"]

    # ★ เฉลย: ซ้ำก็ต่อเมื่อ "การซื้อครั้งนี้" เคยถูกบันทึกไปแล้ว
    #   ไม่ใช่ "กระดาษใบนี้" — ใบเสร็จร้านกับสลิปบัตรของการซื้อเดียวกันต้องได้แต้มครั้งเดียว
    already = session.query(ReceiptRecord).filter_by(source_image_id=purchase_id).count() > 0

    verdict = find_duplicate(session, receipt, member_id=member_id)
    if not verdict.is_duplicate:
        session.add(_to_record(receipt, reading, purchase_id, member_id=member_id))
        session.commit()

    return Outcome(reading.name, purchase_id, already, verdict.is_duplicate, verdict.reason)


def _to_receipt(reading: Reading) -> Receipt:
    return Receipt(
        tenant_id=TENANT,
        merchant=reading.merchant or "ไม่ทราบร้าน",
        merchant_code=reading.merchant_code,
        receipt_no=reading.receipt_no,
        receipt_date=reading.receipt_date,
        receipt_time=reading.receipt_time,
        reference_codes=reading.reference_codes or [],
        total_amount=reading.total_amount,
        source_image_id=reading.name,
    )


def _to_record(receipt: Receipt, reading: Reading, purchase_id: str, *, member_id: int):
    return ReceiptRecord(
        tenant_id=TENANT,
        member_id=member_id,
        content_fingerprint=content_fingerprint(
            TENANT,
            reference_codes=receipt.reference_codes,
            receipt_no=receipt.receipt_no,
            receipt_date=receipt.receipt_date,
            total_amount=receipt.total_amount,
        )
        # เลี่ยงการชน unique constraint ระหว่างวัด: ที่นี่ไม่ได้ทดสอบ constraint
        # แต่ทดสอบ "ตรรกะการตัดสิน" — ต่อท้ายชื่อไฟล์ให้ไม่ซ้ำกันเอง
        + reading.name,
        image_fingerprint=reading.name,
        merchant=receipt.merchant,
        merchant_code=receipt.merchant_code,
        receipt_no=receipt.receipt_no,
        receipt_date=receipt.receipt_date,
        receipt_time=receipt.receipt_time,
        total_amount=receipt.total_amount,
        reference_codes=receipt.reference_codes,
        status=STATUS_AWARDED,
        # ใช้ช่องนี้เก็บ "การซื้อครั้งไหน" เพื่อให้เฉลยตรวจได้ว่าเคยบันทึกไปหรือยัง
        source_image_id=purchase_id,
    )


def _report(outcomes: list[Outcome], unreadable: list[str]) -> None:
    caught = [o for o in outcomes if o.should_be_duplicate and o.was_duplicate]
    missed = [o for o in outcomes if o.missed]
    over = [o for o in outcomes if o.over_blocked]
    expected_dupes = [o for o in outcomes if o.should_be_duplicate]
    expected_new = [o for o in outcomes if not o.should_be_duplicate]

    print(f"{'ใบ':>5} | {'การซื้อ':<18} | {'เฉลย':<8} | {'ระบบ':<8} | ผล")
    print("-" * 86)
    for o in outcomes:
        mark = "★ หลุด" if o.missed else ("จับเกิน" if o.over_blocked else "ถูก")
        print(
            f"{_short(o.name):>5} | {o.purchase_id:<18} | "
            f"{'ซ้ำ' if o.should_be_duplicate else 'ใบใหม่':<8} | "
            f"{'ซ้ำ' if o.was_duplicate else 'ใบใหม่':<8} | {mark}"
        )

    print("-" * 86)
    print(f"  ใบซ้ำที่จับได้   {len(caught):>3}/{len(expected_dupes)}")
    print(f"  ★ ใบซ้ำที่หลุด  {len(missed):>3}/{len(expected_dupes)}   ← ต้องเป็น 0 (ให้แต้มซ้ำ)")
    print(f"  จับเกิน         {len(over):>3}/{len(expected_new)}   ← ลูกค้าเสียแต้มที่ควรได้")
    if unreadable:
        print(f"  (ไม่ได้วัด {len(unreadable)} ใบ เพราะอ่านยอดไม่ได้ตั้งแต่ต้น)")

    for group, title in ((missed, "★ ใบซ้ำที่หลุด"), (over, "ใบที่ถูกจับเกิน")):
        if group:
            print(f"\n{title}:")
            for o in group:
                print(f"    {_short(o.name)} ({o.purchase_id}): {o.reason}")


def _fresh_database():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_member(session: Session) -> int:
    session.add(Tenant(id=TENANT, name="ชุดวัดผล"))
    member = Member(tenant_id=TENANT, line_user_id="U-measure", crm_customer_id="C1")
    session.add(member)
    session.commit()
    return member.id


def _short(name: str) -> str:
    return "#" + name.split("_")[-1].replace(".jpg", "")


def _number(name: str) -> int:
    digits = "".join(char for char in name.split("_")[-1] if char.isdigit())
    return int(digits) if digits else 0


if __name__ == "__main__":
    sys.exit(main())
