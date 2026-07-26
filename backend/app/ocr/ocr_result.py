"""โครงข้อมูลผลลัพธ์ OCR ให้ทุกที่ใช้รูปแบบเดียวกัน"""
from dataclasses import dataclass, field


@dataclass
class TextBox:
    text: str
    bbox: tuple  # (x1, y1, x2, y2)


@dataclass
class OcrResult:
    boxes: list[TextBox] = field(default_factory=list)
