"""สรุปตัวเลขสุขภาพระบบจากตาราง receipts — ให้หน้า admin/health เห็นภาพรวม

★ ทำไมอ่านจากตาราง receipts ไม่ใช่ตัวนับแยก (counter):
  ตัวนับในหน่วยความจำหายเมื่อ restart และไม่ตรงกับความจริงถ้ามีหลาย process
  ส่วนตาราง receipts คือ "ความจริง" ของทุกใบที่ระบบรับ — นับจากตรงนั้นได้เลข
  ที่ถูกต้องเสมอ ไม่ต้องดูแลตัวนับให้ตรงกับความจริงอีกชั้น
  (ที่ volume ของเรา การ COUNT ต่อคำขอถูกและเร็วพอ — ดู CONTEXT ข้อ 3)

★ ตัวเลขที่สำคัญที่สุดคือ dead / failed:
  dead สูง = แต้มของลูกค้าค้างโดยระบบยอมแพ้แล้ว = ต้องมีคนเข้าไปกู้ (excel/revive)
  ตัวเลขนี้ต้องเห็นง่าย ไม่ใช่ซ่อนอยู่ใน log ที่ไม่มีใครเปิด
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.receipts import (
    STATUS_AWARDED, STATUS_DEAD, STATUS_FAILED, STATUS_PENDING, STATUS_REJECTED, ReceiptRecord,
)


@dataclass(frozen=True)
class ScanMetrics:
    """ภาพรวมการสแกนของแบรนด์หนึ่งในช่วงเวลาหนึ่ง"""

    tenant_id: str
    since_days: int
    awarded: int      # ให้แต้มสำเร็จ
    pending: int      # กำลังดำเนินการ
    failed: int       # ส่งไม่สำเร็จ กำลังลองซ้ำ
    dead: int         # ★ ยอมแพ้แล้ว ต้องให้คนกู้
    rejected: int     # ถูกปฏิเสธ (ใบซ้ำ ฯลฯ)

    @property
    def total(self) -> int:
        return self.awarded + self.pending + self.failed + self.dead + self.rejected

    @property
    def award_rate(self) -> float:
        """สัดส่วนใบที่ได้แต้มสำเร็จ จากใบที่ "ควรได้แต้ม" (ไม่นับใบที่ถูกปฏิเสธ)

        คิดจากฐานที่ตัดใบซ้ำออก เพราะใบซ้ำถูกปฏิเสธโดยตั้งใจ ไม่ใช่ความล้มเหลว
        """
        eligible = self.awarded + self.pending + self.failed + self.dead
        return self.awarded / eligible if eligible else 0.0

    @property
    def needs_attention(self) -> bool:
        """มีใบที่ต้องให้คนเข้าไปดูไหม (dead letter ค้างอยู่)"""
        return self.dead > 0


def scan_metrics(session: Session, tenant_id: str, *, since_days: int = 7,
                 today: date | None = None) -> ScanMetrics:
    """นับใบตามสถานะในช่วง since_days วันล่าสุด"""
    today = today or date.today()
    cutoff = datetime.combine(today - timedelta(days=since_days), time.min)

    counts = dict(
        session.execute(
            select(ReceiptRecord.status, func.count())
            .where(ReceiptRecord.tenant_id == tenant_id)
            .where(ReceiptRecord.created_at >= cutoff)
            .group_by(ReceiptRecord.status)
        ).all()
    )

    return ScanMetrics(
        tenant_id=tenant_id,
        since_days=since_days,
        awarded=counts.get(STATUS_AWARDED, 0),
        pending=counts.get(STATUS_PENDING, 0),
        failed=counts.get(STATUS_FAILED, 0),
        dead=counts.get(STATUS_DEAD, 0),
        rejected=counts.get(STATUS_REJECTED, 0),
    )
