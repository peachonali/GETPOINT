"""เก็บไฟล์บนดิสก์ (implementation ของ StoragePort ที่ใช้ตอนนี้)

วันหน้าย้ายไป S3/GCS: เขียนคลาสใหม่ให้ตรง StoragePort แล้วสลับตอนประกอบใน main.py
ชั้นอื่นไม่ต้องแก้แม้แต่บรรทัดเดียว

★ ความปลอดภัยที่ต้องมีในที่เก็บไฟล์: กัน path traversal
  key ที่มี "../" จะพาไฟล์ไปโผล่นอกโฟลเดอร์ที่ตั้งใจ (เขียนทับไฟล์ระบบได้)
  → ตรวจทุกครั้งว่า path สุดท้ายยังอยู่ใต้ base จริง
"""
from __future__ import annotations

from pathlib import Path

from app.storage.storage_interface import StoragePort


class LocalStorage(StoragePort):
    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir).resolve()
        self._base.mkdir(parents=True, exist_ok=True)

    def save(self, key: str, data: bytes) -> str:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key  # คืน key (ไม่ใช่ path เต็ม) — ชั้นบนไม่ควรรู้โครงสร้างดิสก์ของเรา

    def load(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.is_file():
            raise FileNotFoundError(f"ไม่พบไฟล์: {key}")
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def delete(self, key: str) -> bool:
        """ลบไฟล์ · ไม่มีอยู่แล้ว → False (ไม่ error) เพื่อให้ retention รันซ้ำได้"""
        path = self._resolve(key)
        if not path.is_file():
            return False
        path.unlink()
        return True

    def _resolve(self, key: str) -> Path:
        """แปลง key เป็น path จริง + ยืนยันว่าไม่หลุดออกนอก base (กัน path traversal)"""
        candidate = (self._base / key).resolve()
        if not candidate.is_relative_to(self._base):
            raise ValueError(f"key ไม่ถูกต้อง (ชี้ออกนอกที่เก็บไฟล์): {key!r}")
        return candidate
