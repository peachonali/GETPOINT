"""ที่พักงานที่ส่งไม่สำเร็จจริงๆ — ไม่หายไปไหน จนกว่าจะมีคนจัดการ

★ "dead letter" ไม่ใช่ตารางแยก แต่คือใบเสร็จที่ status = DEAD ในตาราง receipts
  (ส่งซ้ำแล้ว loga ปฏิเสธเฉพาะใบนี้เกินเกณฑ์ — ดู send_queue.py)
  ใบพวกนี้ "หยุดส่งซ้ำอัตโนมัติแล้ว" เพื่อไม่บล็อกคิวของใบอื่น แต่ยังอยู่ในระบบ

★ หน้าที่ไฟล์นี้: ให้คน (หน้า admin/ทีมดูแล) เห็นว่ามีใบไหนค้างอยู่บ้าง
  จะได้ตัดสินใจ: กู้ด้วยมือ (excel_export) / แก้ข้อมูลแล้วปลุกกลับ / ยกเลิก

★ ทำไมไม่ทิ้งไปเลย: แต้มที่ค้างคือแต้มของลูกค้าจริง การทิ้งเงียบ = ลูกค้าเสียแต้ม
  โดยไม่มีใครรู้ (สิ่งที่ยอมรับไม่ได้ที่สุดของระบบนี้) · ต้องมีคนเห็นและตัดสินเสมอ
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.receipts import STATUS_DEAD, STATUS_FAILED, ReceiptRecord


@dataclass(frozen=True)
class DeadLetterView:
    """ภาพรวม dead letter ของแบรนด์หนึ่ง — ไว้แสดงหน้า admin/แจ้งเตือน"""

    dead_count: int
    still_retrying_count: int
    records: list[ReceiptRecord]


def list_dead(session: Session, tenant_id: str, *, limit: int = 100) -> DeadLetterView:
    """ใบที่ค้างใน dead letter ของแบรนด์นี้ + จำนวนใบที่ยังลองส่งซ้ำอยู่

    เรียงเก่าสุดก่อน — ใบที่ค้างนานสุดคือใบที่ลูกค้ารอนานสุด ควรถูกจัดการก่อน
    """
    dead_records = list(
        session.scalars(
            select(ReceiptRecord)
            .where(ReceiptRecord.tenant_id == tenant_id)
            .where(ReceiptRecord.status == STATUS_DEAD)
            .order_by(ReceiptRecord.created_at)
            .limit(limit)
        )
    )
    still_retrying = _count(session, tenant_id, STATUS_FAILED)
    return DeadLetterView(
        dead_count=_count(session, tenant_id, STATUS_DEAD),
        still_retrying_count=still_retrying,
        records=dead_records,
    )


def revive(session: Session, receipt_id: int) -> bool:
    """ปลุกใบที่ค้าง DEAD กลับมาให้ส่งซ้ำอีกครั้ง (หลังคนแก้ต้นเหตุแล้ว)

    รีเซ็ต send_attempts เป็น 0 → กลับเข้าคิวส่งซ้ำปกติ
    คืน False ถ้าไม่พบใบหรือใบนั้นไม่ได้อยู่สถานะ DEAD (กันปลุกใบที่ได้แต้มแล้วโดยพลาด)
    """
    record = session.get(ReceiptRecord, receipt_id)
    if record is None or record.status != STATUS_DEAD:
        return False

    record.status = STATUS_FAILED
    record.send_attempts = 0
    session.commit()
    return True


def _count(session: Session, tenant_id: str, status: str) -> int:
    return session.scalar(
        select(func.count())
        .select_from(ReceiptRecord)
        .where(ReceiptRecord.tenant_id == tenant_id)
        .where(ReceiptRecord.status == status)
    ) or 0
