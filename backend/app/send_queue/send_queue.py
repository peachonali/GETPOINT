"""ส่งแต้มที่ค้างอยู่ (FAILED) เข้า CRM ใหม่ — ตัวกู้คืนอัตโนมัติเมื่อ loga ฟื้น

★ ทำไมไม่มีตารางคิวแยก:
  ตาราง receipts ที่สถานะ FAILED "เป็นคิวอยู่แล้ว" — มันคือรายการงานที่ต้องส่งซ้ำ
  พร้อม reference เดิม (ยิงซ้ำไม่ได้แต้มซ้ำ · ADR 0003 #7)
  สร้างตารางใหม่ = เก็บข้อมูลเดียวกันสองที่ แล้ววันหนึ่งมันจะไม่ตรงกัน (DEV ข้อ 1.4)

★ ปลอดภัยเพราะ idempotent:
  ส่งด้วย crm_reference เดิมเสมอ · ถ้ารอบก่อนจริงๆ แล้วสำเร็จแต่เราบันทึกไม่ทัน
  (ระบบล่มตอนนั้นพอดี) loga จะไม่ให้แต้มซ้ำ เราแค่ได้ยอดสะสมกลับมาแล้ว mark AWARDED

★ ผ่าน CrmPort ที่ห่อ circuit breaker แล้ว (ResilientCrm):
  ถ้า loga ยังล่ม วงจรจะเปิด แล้ว resend รอบนี้เลิกทันที ไม่กระหน่ำซ้ำ
  งานยังเป็น FAILED รอรอบหน้า

⚠ ยังไม่มี "เลิกส่งหลังลอง N รอบ" (dead letter) — ใบที่ส่งไม่ได้จริงๆ จะถูกลองเรื่อยๆ
  ตราบใดที่ยังลองแล้วเป็น error ที่ retryable · การตัดสินว่า "พอแล้ว ให้คนดู" เป็นงานถัดไป
  (ตอนนี้ทางออกคือ excel_export ให้คนกู้ด้วยมือ — ปลอดภัยพอสำหรับตอนนี้)
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.members import Member
from app.database.receipts import STATUS_AWARDED, STATUS_FAILED, ReceiptRecord
from app.external.crm_interface import CrmPort
from app.observability.logging import get_logger, log_context
from app.points.point_rate import points_for
from app.reliability.errors import GetpointError

log = get_logger(__name__)

#: ข้อความที่ลูกค้าจะเห็นในประวัติแต้มของตัวเอง (เหมือนตอนส่งครั้งแรก)
_REMARK = "สะสมแต้มจากใบเสร็จ {merchant}"


@dataclass(frozen=True)
class ResendSummary:
    """สรุปผลการส่งซ้ำ 1 รอบ — ไว้ log/แสดงหน้า admin ว่ากู้คืนได้กี่ใบ เหลือค้างกี่ใบ"""

    attempted: int
    succeeded: int
    still_failing: int


class PointResender:
    """ประกอบ dependency ครั้งเดียว แล้วเรียก run() ซ้ำเป็นรอบๆ (จาก worker/cron)"""

    def __init__(self, crm: CrmPort, *, formula_id: str, batch_size: int = 50) -> None:
        self._crm = crm
        self._formula_id = formula_id
        self._batch_size = batch_size

    def run(self, session: Session) -> ResendSummary:
        """ส่งใบที่ค้างทั้งหมดในรอบนี้ (ไม่เกิน batch_size ใบ) · คืนสรุปผล

        หยุดทั้ง batch ทันทีที่เจอ error ที่ "ลองใหม่ทีหลังค่อยหาย" (เช่นวงจรเปิด)
        เพราะถ้า loga ล่ม ใบถัดๆ ไปก็จะล่มเหมือนกัน — ลองต่อเปล่าประโยชน์
        """
        pending = self._fetch_failed(session)
        succeeded = 0

        for index, record in enumerate(pending):
            member = session.get(Member, record.member_id)
            if member is None or not member.crm_customer_id:
                continue  # สมาชิกหาย/ยังไม่ผูก CRM — ข้าม ไม่ใช่หน้าที่ resend แก้

            try:
                self._resend_one(session, record, member.crm_customer_id)
                succeeded += 1
            except GetpointError as exc:
                log.warning("ส่งซ้ำไม่สำเร็จ หยุดรอบนี้", extra={"detail": str(exc)})
                # ใบที่เหลือในรอบนี้ยังไม่ได้ลอง = ยังค้างต่อ
                return ResendSummary(len(pending), succeeded, len(pending) - succeeded)

        return ResendSummary(len(pending), succeeded, len(pending) - succeeded)

    def _fetch_failed(self, session: Session) -> list[ReceiptRecord]:
        statement = (
            select(ReceiptRecord)
            .where(ReceiptRecord.status == STATUS_FAILED)
            .order_by(ReceiptRecord.created_at)  # เก่าสุดก่อน — ลูกค้าที่รอนานสุดได้ก่อน
            .limit(self._batch_size)
        )
        return list(session.scalars(statement))

    def _resend_one(self, session: Session, record: ReceiptRecord, customer_id: str) -> None:
        with log_context(receipt_id=record.id, tenant_id=record.tenant_id):
            reference = record.crm_reference
            award = self._crm.add_points(
                customer_id=customer_id,
                cost=record.total_amount,
                formula_id=self._formula_id,
                remark=_REMARK.format(merchant=record.merchant or "ไม่ทราบร้าน"),
                reference=reference,   # ★ reference เดิม → loga ไม่ให้แต้มซ้ำ
            )

            record.status = STATUS_AWARDED
            record.points_awarded = points_for(record.total_amount)
            session.commit()
            log.info("ส่งซ้ำสำเร็จ", extra={"reference": reference, "balance": award.points_balance})
