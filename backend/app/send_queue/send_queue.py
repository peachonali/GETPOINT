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

★ แยก 2 สาเหตุของการล้ม ชัดเจน (สำคัญมาก):
    ระบบล่ม (retryable: timeout/วงจรเปิด) → หยุดทั้ง batch · ไม่นับเป็นความผิดของใบนี้
                                            ใบถัดไปก็จะล่มเหมือนกัน ลองต่อเปล่าประโยชน์
    ปฏิเสธเฉพาะใบ (ไม่ retryable: loga ปฏิเสธ) → นับ send_attempts +1 · ครบเกณฑ์ย้ายไป DEAD
                                                แล้วไปใบถัดไป (ใบพังใบเดียวต้องไม่บล็อกทั้งคิว)

  ถ้าไม่แยก: ใบที่ loga ปฏิเสธตลอด (เช่น reference มีปัญหา) จะเป็นใบเก่าสุดที่ล้มก่อน
  แล้วบล็อกใบอื่นทั้งคิวไปตลอดกาล → dead letter คือทางออกของเคสนี้
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.members import Member
from app.database.receipts import STATUS_AWARDED, STATUS_DEAD, STATUS_FAILED, ReceiptRecord
from app.external.crm_interface import CrmPort
from app.observability.logging import get_logger, log_context
from app.points.point_rate import points_for
from app.reliability.errors import GetpointError

log = get_logger(__name__)

#: ข้อความที่ลูกค้าจะเห็นในประวัติแต้มของตัวเอง (เหมือนตอนส่งครั้งแรก)
_REMARK = "สะสมแต้มจากใบเสร็จ {merchant}"

#: ปฏิเสธเฉพาะใบนี้เกินกี่ครั้ง → ยอมแพ้ ย้ายไป DEAD ให้คนดู
#: 5 ครั้ง = เผื่อ loga สะดุดชั่วคราวหลายรอบ แต่ไม่ลองไปตลอดกาลจนบล็อกคิว
_MAX_SEND_ATTEMPTS = 5


@dataclass(frozen=True)
class ResendSummary:
    """สรุปผลการส่งซ้ำ 1 รอบ — ไว้ log/แสดงหน้า admin ว่ากู้คืนได้กี่ใบ เหลือค้างกี่ใบ"""

    attempted: int
    succeeded: int
    still_failing: int
    #: ใบที่ถูกย้ายไป DEAD ในรอบนี้ (ปฏิเสธเฉพาะใบเกินเกณฑ์) — ต้องให้คนดู
    dead_lettered: int = 0


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
        dead = 0

        for record in pending:
            member = session.get(Member, record.member_id)
            if member is None or not member.crm_customer_id:
                continue  # สมาชิกหาย/ยังไม่ผูก CRM — ข้าม ไม่ใช่หน้าที่ resend แก้

            try:
                self._resend_one(session, record, member.crm_customer_id)
                succeeded += 1
            except GetpointError as exc:
                if exc.retryable:
                    # ★ ระบบล่ม (timeout/วงจรเปิด) — ไม่ใช่ความผิดของใบนี้
                    #   หยุดทั้ง batch · ใบถัดไปก็จะล่มเหมือนกัน ลองต่อเปล่าประโยชน์
                    log.warning("ระบบปลายทางยังล่ม หยุดรอบนี้", extra={"detail": str(exc)})
                    remaining = len(pending) - succeeded - dead
                    return ResendSummary(len(pending), succeeded, remaining, dead)

                # ★ loga ปฏิเสธเฉพาะใบนี้ (เช่น reference มีปัญหา) — นับ แล้วไปใบถัดไป
                #   ใบพังใบเดียวต้องไม่บล็อกทั้งคิว
                if self._mark_failure(session, record, str(exc)):
                    dead += 1

        remaining = len(pending) - succeeded - dead
        return ResendSummary(len(pending), succeeded, remaining, dead)

    def _mark_failure(self, session: Session, record: ReceiptRecord, detail: str) -> bool:
        """นับความล้มเหลวเฉพาะใบ · ครบเกณฑ์ → ย้ายไป DEAD · คืน True ถ้าเพิ่งย้าย"""
        record.send_attempts += 1
        became_dead = record.send_attempts >= _MAX_SEND_ATTEMPTS
        if became_dead:
            record.status = STATUS_DEAD
            log.error(
                "ย้ายใบเสร็จไป dead letter — ปฏิเสธซ้ำเกินเกณฑ์",
                extra={"receipt_id": record.id, "attempts": record.send_attempts, "detail": detail},
            )
        session.commit()
        return became_dead

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
