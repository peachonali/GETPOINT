"""สัญญา (Port) ของที่เก็บไฟล์ — วันหน้าเปลี่ยน local → S3/GCS ไม่ต้องรื้อ"""
from abc import ABC, abstractmethod


class StoragePort(ABC):
    @abstractmethod
    def save(self, key: str, data: bytes) -> str:
        """เก็บไฟล์ → คืน key/URL"""
        raise NotImplementedError

    @abstractmethod
    def load(self, key: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> bool:
        """ลบไฟล์ · คืน True ถ้ามีไฟล์ให้ลบ, False ถ้าไม่มีอยู่แล้ว (ไม่ถือเป็น error)

        ใช้กับ retention (PDPA — ลบรูปใบเสร็จตามกำหนดอายุ)
        ลบของที่ไม่มีอยู่แล้วต้องไม่พัง เพราะ retention อาจรันซ้ำบนของที่ลบไปแล้ว
        """
        raise NotImplementedError
