"""เก็บ "ข้อความ OCR ดิบ" ของแต่ละใบไว้ — สำหรับตรวจสอบย้อนหลัง + ปรับปรุง OCR

★ ทำไมต้องเก็บ (2 เหตุผล):
  1. Audit: ลูกค้าทักว่า "ได้แต้มไม่ตรง" → เปิดดูได้ว่า OCR อ่านอะไรมา ระบบตัดสินจากอะไร
     (รูปต้นฉบับก็มี แต่ข้อความดิบบอกได้ทันทีว่าพลาดตรง "อ่าน" หรือตรง "ตีความ")
  2. ปรับ OCR/template: ข้อความจริงจากหน้างานคือวัตถุดิบชั้นดีเวลาแก้กฎ
     (เหมือน golden set แต่โตเองจากของจริงทุกใบ)

★ เก็บผ่าน StoragePort เดียวกับรูป — วันหน้าย้าย S3 ก็ไปด้วยกัน
  แยก key ด้วยนามสกุล .txt (รูปเป็น .jpg) ใต้ tenant เดียวกัน

★ PDPA: ข้อความ OCR อาจมีข้อมูลส่วนบุคคล (ชื่อบนบัตร ฯลฯ) → ถูกลบพร้อมรูปตอน retention
  (retention ลบทั้งโฟลเดอร์ tenant/receipt — ครอบทั้ง .jpg และ .txt)

⚠ เก็บแบบ "ล้มแล้วไม่ล้มงาน": ถ้าเก็บ text ไม่สำเร็จ ต้องไม่ทำให้การให้แต้มพัง
  (เป็นข้อมูลเสริมเพื่อ debug ไม่ใช่เส้นทางหลัก) — ผู้เรียกจับ error เอง
"""
from __future__ import annotations

from app.observability.logging import get_logger
from app.storage.storage_interface import StoragePort

log = get_logger(__name__)

#: วางคู่กับรูป (receipts/{tenant}/{id}.jpg) แต่เป็น .txt
_KEY_TEMPLATE = "receipts/{tenant_id}/{receipt_id}.txt"


class OcrTextStore:
    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage

    def put(self, tenant_id: str, receipt_id: str, lines: list[str]) -> str:
        """เก็บข้อความ OCR (ทีละบรรทัด) → คืน key ไว้อ้างอิง

        เก็บเป็น UTF-8 บรรทัดต่อบรรทัด — เปิดอ่านด้วยตาได้ตรงๆ เวลา debug
        """
        key = self._key(tenant_id, receipt_id)
        self._storage.save(key, "\n".join(lines).encode("utf-8"))
        return key

    def get(self, tenant_id: str, receipt_id: str) -> list[str]:
        raw = self._storage.load(self._key(tenant_id, receipt_id))
        return raw.decode("utf-8").splitlines()

    @staticmethod
    def _key(tenant_id: str, receipt_id: str) -> str:
        return _KEY_TEMPLATE.format(tenant_id=tenant_id, receipt_id=receipt_id)
