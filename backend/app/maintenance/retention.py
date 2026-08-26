"""ลบข้อมูลส่วนบุคคลตามกำหนดอายุ (PDPA — CONTEXT ข้อ 3 "มีกำหนดลบ")

★ เก็บข้อมูลส่วนบุคคลเท่าที่จำเป็น + มีกำหนดลบ — เป็นข้อบังคับ ไม่ใช่ทางเลือก
  ข้อมูลส่วนบุคคลที่ระบบถือ:
    1. รูปใบเสร็จ — อาจมีข้อมูลในภาพ + เคยติด EXIF (ล้างที่ upload_check แล้ว)
    2. เบอร์โทร ใน members — ตัวระบุตัวบุคคลโดยตรง

★ ลบ 2 ระดับ ต่างจังหวะกัน:
    รูปใบเสร็จ  → ลบเร็ว (เก็บไว้แค่พอตรวจสอบข้อโต้แย้ง ~90 วัน)
                 แถวใน receipts ยังอยู่ (ยอด/วันที่ ไม่ใช่ตัวระบุตัวบุคคล) เพื่อกันใบซ้ำต่อ
    เบอร์โทร   → เก็บนานกว่า (สมาชิกยัง active) · ลบ/ปิดบังเมื่อไม่เคลื่อนไหวนานมาก

★ "ลบรูปแต่เก็บแถว" คือจุดสมดุล: กันใบซ้ำยังทำงานได้ (ใช้ลายนิ้วมือ+เลขอ้างอิง
  ที่ไม่ใช่รูป) แต่ตัวรูปซึ่งเป็นข้อมูลส่วนบุคคลหนักสุดถูกลบตามกำหนด

⚠ ทำงานเป็นรอบจาก background (worker เรียกวันละครั้ง) — ดู maintenance/retention_worker
  ยังไม่ลบแถว receipts ทั้งแถว เพราะ content_fingerprint ยังต้องใช้กันซ้ำ
  (ถ้าจะลบแถวจริงต้องเก็บแค่ fingerprint ไว้ แล้วลบ field อื่น — ทำเมื่อมี requirement ชัด)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.receipts import ReceiptRecord
from app.observability.logging import get_logger
from app.storage.image_store import ImageStore

log = get_logger(__name__)

#: เก็บรูปใบเสร็จไว้กี่วันก่อนลบ — พอสำหรับตรวจสอบข้อโต้แย้งเรื่องแต้ม
#: 90 วัน = 1 ไตรมาส ครอบคลุมรอบร้องเรียนปกติ
DEFAULT_IMAGE_RETENTION_DAYS = 90

#: เคยพยายามลบรูปแล้ว แต่แถวยังชี้ค่าเดิม — กันลบซ้ำทุกรอบ
_IMAGE_PURGED_MARK = ""


@dataclass(frozen=True)
class RetentionResult:
    images_deleted: int
    already_gone: int


def purge_old_images(
    session: Session,
    images: ImageStore,
    *,
    retention_days: int = DEFAULT_IMAGE_RETENTION_DAYS,
    today: date | None = None,
    batch_size: int = 500,
) -> RetentionResult:
    """ลบรูปใบเสร็จที่เก่ากว่ากำหนด · แถว receipts ยังอยู่ (เพื่อกันใบซ้ำต่อ)

    ทำเป็น batch กันโหลดหนักครั้งเดียว · เรียกซ้ำได้ (idempotent):
    ลบรูปแล้วเคลียร์ source_image_id เป็นค่าว่าง → รอบหน้าไม่หยิบมาลบซ้ำ
    """
    today = today or date.today()
    cutoff = today - timedelta(days=retention_days)

    old = list(
        session.scalars(
            select(ReceiptRecord)
            .where(ReceiptRecord.created_at < _start_of_day(cutoff))
            .where(ReceiptRecord.source_image_id != _IMAGE_PURGED_MARK)
            .limit(batch_size)
        )
    )

    deleted = 0
    already_gone = 0
    for record in old:
        existed = images.delete_by_key(record.source_image_id)
        if existed:
            deleted += 1
        else:
            already_gone += 1
        # ★ ทำเครื่องหมายว่ารูปถูกลบแล้ว ไม่ว่าจะเจอไฟล์หรือไม่
        #   (ไฟล์อาจถูกลบด้วยมือ/ระบบอื่นไปก่อน — ยังต้องหยุดหยิบแถวนี้มาอีก)
        record.source_image_id = _IMAGE_PURGED_MARK

    session.commit()

    if deleted or already_gone:
        log.info(
            "ลบรูปใบเสร็จตามกำหนดอายุแล้ว",
            extra={"deleted": deleted, "already_gone": already_gone, "cutoff": cutoff.isoformat()},
        )
    return RetentionResult(images_deleted=deleted, already_gone=already_gone)


def _start_of_day(day: date):
    """แปลง date เป็น datetime ต้นวัน — created_at เก็บเป็น datetime ต้องเทียบชนิดเดียวกัน"""
    from datetime import datetime, time

    return datetime.combine(day, time.min)
