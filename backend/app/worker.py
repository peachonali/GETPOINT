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
import time
from types import FrameType

from app.composition import build_resender, build_scan_runner, build_shared
from app.config.settings import settings
from app.database.db import SessionLocal
from app.maintenance.retention import purge_old_images
from app.observability.logging import get_logger, setup_logging

log = get_logger(__name__)

#: worker รอคิวสูงสุดกี่วินาทีต่อรอบ ก่อนวนกลับมาเช็คว่าถูกสั่งปิดหรือยัง
POLL_BLOCK_SECONDS = 5

#: ส่งใบที่ค้าง (FAILED) ซ้ำทุกกี่วินาที — ทำตอน worker ว่างจากงานสแกน
#: 60 วิ = ไม่ถี่จนกวน loga ตอนมันเพิ่งฟื้น แต่เร็วพอที่ลูกค้าไม่ต้องรอนานหลัง loga กลับมา
RESEND_INTERVAL_SECONDS = 60

#: ลบรูปเก่าตามกำหนด (PDPA) ทุกกี่วินาที — วันละครั้งพอ (ข้อมูลไม่ได้เพิ่มเร็ว)
RETENTION_INTERVAL_SECONDS = 24 * 60 * 60


class Worker:
    def __init__(self) -> None:
        self._running = True
        self._last_resend = 0.0  # เวลาล่าสุดที่ส่งใบค้างซ้ำ (monotonic)
        self._last_purge = 0.0   # เวลาล่าสุดที่ลบรูปเก่า (monotonic)

    def request_stop(self, signum: int, _frame: FrameType | None) -> None:
        """ตัวรับสัญญาณปิด — แค่ยกธง ไม่ตัดงานที่กำลังทำอยู่กลางคัน"""
        log.info("ได้รับสัญญาณปิด กำลังจะหยุดหลังงานปัจจุบันเสร็จ", extra={"signal": signum})
        self._running = False

    def run(self) -> None:
        if SessionLocal is None:
            raise RuntimeError("ยังไม่ได้ตั้ง DATABASE_URL ใน .env — worker ทำงานไม่ได้")

        shared = build_shared(settings)
        runner = build_scan_runner(shared)
        resender = build_resender(shared)
        self._images = shared.images
        self._last_resend = 0.0
        log.info("GETPOINT worker เริ่มทำงาน รอรับงานจากคิว")

        try:
            while self._running:
                job = shared.job_queue.dequeue(block_seconds=POLL_BLOCK_SECONDS)
                if job is None:
                    # ว่างจากงานสแกน — ใช้จังหวะนี้ทำงานเบื้องหลัง (ถ้าถึงรอบ)
                    self._maybe_resend(resender)
                    self._maybe_purge_images()
                    continue

                # session ใหม่ต่อ 1 งาน — งานที่พังจะไม่ทิ้ง transaction ค้างให้งานถัดไป
                with SessionLocal() as session:
                    runner.run(session, job)
        finally:
            shared.close()
            log.info("GETPOINT worker หยุดทำงานแล้ว")

    def _maybe_resend(self, resender) -> None:
        """ส่งใบที่ค้างซ้ำ ถ้าครบรอบแล้ว — ไม่ให้ล้มทั้ง worker ถ้า resend พัง

        ★ resend คือ "งานเสริม" ของ worker · ถ้ามันพัง (DB สะดุด ฯลฯ) ต้องไม่ทำให้
          worker ตายจนรับงานสแกนใหม่ไม่ได้ → จับ error ทุกชนิดไว้ที่นี่
        """
        now = time.monotonic()
        if now - self._last_resend < RESEND_INTERVAL_SECONDS:
            return
        self._last_resend = now

        try:
            with SessionLocal() as session:
                summary = resender.run(session)
            if summary.succeeded or summary.dead_lettered:
                log.info(
                    "ส่งใบค้างซ้ำแล้ว",
                    extra={
                        "succeeded": summary.succeeded,
                        "still_failing": summary.still_failing,
                        "dead": summary.dead_lettered,
                    },
                )
        except Exception as exc:  # noqa: BLE001 — งานเสริมต้องไม่ทำ worker ตาย
            log.warning("ส่งใบค้างซ้ำล้มเหลว (จะลองใหม่รอบหน้า)", extra={"detail": str(exc)})

    def _maybe_purge_images(self) -> None:
        """ลบรูปเก่าตามกำหนด PDPA ถ้าครบรอบ — งานเสริม ล้มแล้วต้องไม่ทำ worker ตาย"""
        now = time.monotonic()
        if now - self._last_purge < RETENTION_INTERVAL_SECONDS:
            return
        self._last_purge = now

        try:
            with SessionLocal() as session:
                result = purge_old_images(session, self._images)
            if result.images_deleted:
                log.info("ลบรูปเก่าตามกำหนด PDPA", extra={"deleted": result.images_deleted})
        except Exception as exc:  # noqa: BLE001
            log.warning("ลบรูปเก่าล้มเหลว (จะลองใหม่รอบหน้า)", extra={"detail": str(exc)})


def main() -> None:
    setup_logging()
    worker = Worker()

    # SIGTERM = docker/k8s สั่งปิด · SIGINT = Ctrl+C ตอน dev
    signal.signal(signal.SIGTERM, worker.request_stop)
    signal.signal(signal.SIGINT, worker.request_stop)

    worker.run()


if __name__ == "__main__":
    sys.exit(main())
