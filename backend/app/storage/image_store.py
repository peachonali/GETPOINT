"""เก็บ/ดึงรูปใบเสร็จต้นฉบับ — หลักฐานสำหรับตรวจสอบย้อนหลัง (audit trail)

ทำไมต้องเก็บรูปไว้:
    ลูกค้าทักว่า "ได้แต้มไม่ตรง" → ต้องเปิดรูปใบเดิมมาดูได้ว่าระบบอ่านผิดหรือลูกค้าจำผิด
    และเป็นวัตถุดิบของ golden set (tests/fixtures/receipts) เวลาปรับ OCR/template

★ รูปใบเสร็จ = ข้อมูลส่วนบุคคล (PDPA) → เก็บเท่าที่จำเป็น มีกำหนดลบ
  (การลบตามอายุเป็นหน้าที่ของ background/retention_worker.py — Step 7)

ห่อ StoragePort อีกชั้นเพื่อ "ตั้งชื่อ key ให้เป็นระบบ" ที่เดียว
ชั้นบนส่งแค่ tenant_id + receipt_id ไม่ต้องรู้ว่าไฟล์ไปอยู่ตรงไหน
"""
from __future__ import annotations

from app.storage.storage_interface import StoragePort

#: แยกโฟลเดอร์ตาม tenant ตั้งแต่แรก — วันมีลูกค้ารายที่ 2 ข้อมูลไม่ปนกัน
#: และลบข้อมูลของแบรนด์เดียวได้โดยไม่กระทบคนอื่น
_KEY_TEMPLATE = "receipts/{tenant_id}/{receipt_id}.jpg"


class ImageStore:
    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage

    def put(self, tenant_id: str, receipt_id: str, image: bytes) -> str:
        """เก็บรูปต้นฉบับ (ที่ผ่าน upload_check แล้ว) → คืน key ไว้อ้างอิงใน DB"""
        key = self._key(tenant_id, receipt_id)
        self._storage.save(key, image)
        return key

    def get(self, tenant_id: str, receipt_id: str) -> bytes:
        return self._storage.load(self._key(tenant_id, receipt_id))

    def delete_by_key(self, key: str) -> bool:
        """ลบรูปด้วย key ที่เก็บไว้ใน DB (source_image_id) — ใช้ตอน retention

        รับ key ตรงๆ เพราะ retention มี key จาก DB อยู่แล้ว ไม่ต้องประกอบใหม่จาก
        tenant+receipt (และ key อาจมาจากรูปแบบเก่าถ้าเปลี่ยน template ในอนาคต)
        """
        return self._storage.delete(key)

    @staticmethod
    def _key(tenant_id: str, receipt_id: str) -> str:
        return _KEY_TEMPLATE.format(tenant_id=tenant_id, receipt_id=receipt_id)
