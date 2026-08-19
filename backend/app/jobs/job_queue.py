"""คิวงานสแกน — web โยนงานเข้า / worker ดึงงานออก (ผ่าน Redis)

★ นี่คือหัวใจของ async job (ADR 0002):
    web รับรูป → โยนเข้าคิว → ตอบ 202 ทันที (< 500ms)
    worker ดึงไปทำงานหนัก (OpenCV/OCR) แล้วแจ้งผลทาง LINE Push

ทำไม Redis list ไม่ใช่ Kafka/SQS: ที่ปริมาณของเรา (< 2 RPS) Redis เหลือเฟือ
และเรามี Redis อยู่แล้วสำหรับ OTP/rate limit — ไม่ต้องเพิ่ม infra (blueprint ส่วนที่ 3)

★ ใช้ BLPOP (บล็อกรอ) ไม่ใช่วนถาม: worker หลับรอจนมีงานจริง ไม่กิน CPU เปล่า
  และถ้ามี worker หลายตัว Redis แจกงานให้ตัวเดียวเท่านั้น (ไม่ทำซ้ำ)
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from redis import Redis

from app.observability.logging import get_logger

log = get_logger(__name__)

#: คิวเดียวสำหรับงานสแกนทั้งระบบ (ทุก tenant) — แยกคิวต่อ tenant ค่อยทำเมื่อมีลูกค้าหลายราย
QUEUE_KEY = "queue:scan"

#: worker รอสูงสุดกี่วินาทีต่อรอบก่อนวนกลับมาเช็คสัญญาณปิดโปรแกรม
DEFAULT_BLOCK_SECONDS = 5


@dataclass(frozen=True)
class ScanJob:
    """ใบสั่งงาน 1 ใบ — ข้อมูลน้อยที่สุดที่ worker ต้องใช้เพื่อทำงานต่อ

    ★ เก็บ "ที่อยู่ของรูป" (image_key) ไม่ใช่ตัวรูป — ไม่ยัดไฟล์เป็นล้านไบต์ลงคิว
      (Redis จะบวม และคิวควรเก็บ "งาน" ไม่ใช่ "ข้อมูล")
    """

    job_id: str
    tenant_id: str
    member_id: int
    receipt_id: str
    image_key: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "ScanJob":
        return cls(**json.loads(raw))


class JobQueue:
    def __init__(self, redis: Redis, *, queue_key: str = QUEUE_KEY) -> None:
        self._redis = redis
        self._queue_key = queue_key

    def enqueue(self, job: ScanJob) -> None:
        """โยนงานเข้าท้ายคิว (เรียกจาก web — ต้องเร็ว ห้ามบล็อก)"""
        self._redis.rpush(self._queue_key, job.to_json())
        log.info("เข้าคิวสแกนแล้ว", extra={"job_id": job.job_id, "receipt_id": job.receipt_id})

    def dequeue(self, *, block_seconds: int = DEFAULT_BLOCK_SECONDS) -> ScanJob | None:
        """ดึงงานหัวคิว (เรียกจาก worker) · ไม่มีงานภายในเวลาที่รอ → None

        คืน None ไม่ใช่ error เพราะ "ไม่มีงาน" เป็นสถานการณ์ปกติของ worker
        """
        popped = self._redis.blpop([self._queue_key], timeout=block_seconds)
        if popped is None:
            return None

        _key, raw = popped
        try:
            return ScanJob.from_json(raw)
        except (ValueError, TypeError) as exc:
            # ข้อมูลในคิวเสีย — ทิ้งแล้วไปต่อ ดีกว่าให้ worker ตายทั้งตัว
            # (ของจริงที่ควรกู้ได้จะไปอยู่ dead_letter ใน Step 6)
            log.error("งานในคิวอ่านไม่ได้ ข้ามไป", extra={"detail": str(exc)})
            return None

    def pending_count(self) -> int:
        """จำนวนงานค้างคิว — ใช้ดูสุขภาพระบบ/หน้า admin"""
        return self._redis.llen(self._queue_key)
