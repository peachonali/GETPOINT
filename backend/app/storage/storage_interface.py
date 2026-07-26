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
