"""สัญญา (Port) ของ OCR — OCR ตัวไหนก็ต้องทำตามนี้ เพื่อให้สลับ engine ได้โดยไม่แก้ที่อื่น"""
from abc import ABC, abstractmethod
from .ocr_result import OcrResult


class OcrEngine(ABC):
    @abstractmethod
    def read(self, image_bytes: bytes) -> OcrResult:
        """อ่านรูป → คืนข้อความ + ตำแหน่ง (bbox)"""
        raise NotImplementedError
