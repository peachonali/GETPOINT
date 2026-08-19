"""★ worker process — ดึงงานสแกนจากคิวมาประมวลผล

แยกจาก web (Bulkhead — ADR 0002): OCR กิน CPU หนัก ถ้ารันรวมกับ web
จะลากให้ทั้ง API ช้าตามหรือตายไปด้วย · แยก process แล้วต่อให้ worker ตาย
ลูกค้าก็ยังส่งใบเสร็จเข้าคิวได้ตามปกติ (งานจะถูกทำเมื่อ worker กลับมา)

รันด้วย: python -m app.worker   (docker-compose มี service แยกให้แล้ว)

★ ปิดโปรแกรมอย่างสุภาพ (graceful shutdown):
  ได้สัญญาณปิด → ทำงานใบที่ถืออยู่ให้จบก่อน แล้วค่อยออก
  ถ้าตายกลางคัน ใบนั้นจะหายไป (ยังไม่มี retry — Step 6 จะเพิ่ม dead letter)
"""
from __future__ import annotations

import signal
import sys
from types import FrameType

from app.composition import build_scan_runner, build_shared
from app.config.settings import settings
from app.database.db import SessionLocal
from app.observability.logging import get_logger, setup_logging

log = get_logger(__name__)

#: worker รอคิวสูงสุดกี่วินาทีต่อรอบ ก่อนวนกลับมาเช็คว่าถูกสั่งปิดหรือยัง
POLL_BLOCK_SECONDS = 5


class Worker:
    def __init__(self) -> None:
        self._running = True

    def request_stop(self, signum: int, _frame: FrameType | None) -> None:
        """ตัวรับสัญญาณปิด — แค่ยกธง ไม่ตัดงานที่กำลังทำอยู่กลางคัน"""
        log.info("ได้รับสัญญาณปิด กำลังจะหยุดหลังงานปัจจุบันเสร็จ", extra={"signal": signum})
        self._running = False

    def run(self) -> None:
        if SessionLocal is None:
            raise RuntimeError("ยังไม่ได้ตั้ง DATABASE_URL ใน .env — worker ทำงานไม่ได้")

        shared = build_shared(settings)
        runner = build_scan_runner(shared)
        log.info("GETPOINT worker เริ่มทำงาน รอรับงานจากคิว")

        try:
            while self._running:
                job = shared.job_queue.dequeue(block_seconds=POLL_BLOCK_SECONDS)
                if job is None:
                    continue  # ไม่มีงานในรอบนี้ — วนไปเช็คสัญญาณปิดแล้วรอต่อ

                # session ใหม่ต่อ 1 งาน — งานที่พังจะไม่ทิ้ง transaction ค้างให้งานถัดไป
                with SessionLocal() as session:
                    runner.run(session, job)
        finally:
            shared.close()
            log.info("GETPOINT worker หยุดทำงานแล้ว")


def main() -> None:
    setup_logging()
    worker = Worker()

    # SIGTERM = docker/k8s สั่งปิด · SIGINT = Ctrl+C ตอน dev
    signal.signal(signal.SIGTERM, worker.request_stop)
    signal.signal(signal.SIGINT, worker.request_stop)

    worker.run()


if __name__ == "__main__":
    sys.exit(main())
