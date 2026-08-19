"""OCR ปลอมสำหรับเทส/ต่อเส้น (implementation ของ OcrEngine)

★ บทบาทใน Step 3: เป็น "ตัวแทนชั่วคราว" ของ OCR จริง เพื่อพิสูจน์ว่าสายทั้งหมด
  (รับรูป → คิว → worker → คิดแต้ม → ส่ง CRM → LINE Push) ต่อกันได้จริง
  ก่อนจะลงแรงกับ OpenCV/PaddleOCR ใน Step 4 — ถ้าสถาปัตยกรรมมีปัญหา จะได้รู้ก่อน

⚠ ห้ามใช้ตัวนี้บน production — main.py/worker.py เลือก engine จริงตาม config
"""
from __future__ import annotations

from app.ocr.ocr_interface import OcrEngine
from app.ocr.ocr_result import OcrResult, TextBox

#: ข้อความจำลองแบบใบเสร็จไทยทั่วไป — มีทั้งชื่อร้าน เลขที่ วันที่ ยอดย่อย VAT ยอดรวม
#: (ครบชุดที่ template_rules จะใช้ตรวจ "ยอดย่อย + VAT = ยอดรวม" ใน Step 5)
DEFAULT_LINES: list[tuple[str, tuple[int, int, int, int]]] = [
    ("ร้านทดสอบ สาขาทดลอง", (40, 30, 360, 70)),
    ("เลขที่ INV-0001", (40, 90, 300, 120)),
    ("วันที่ 01/08/2026", (40, 130, 300, 160)),
    ("ยอดรวมก่อนภาษี 233.64", (40, 260, 380, 295)),
    ("ภาษีมูลค่าเพิ่ม 7% 16.36", (40, 300, 380, 335)),
    ("รวมทั้งสิ้น 250.00", (40, 350, 380, 395)),
]


class FakeOcr(OcrEngine):
    """คืนผลคงที่เสมอ — ไม่สนใจว่ารูปที่ส่งมาเป็นอะไร

    รับ lines เข้ามาแทนได้ เพื่อให้เทสจำลองเคสอื่น (อ่านไม่ออก/ยอดแปลก) ได้ด้วย
    """

    def __init__(self, lines: list[tuple[str, tuple[int, int, int, int]]] | None = None) -> None:
        self._lines = DEFAULT_LINES if lines is None else lines
        #: นับจำนวนครั้งที่ถูกเรียก — ให้เทสยืนยันว่า pipeline เรียก OCR จริง
        self.calls = 0

    def read(self, image_bytes: bytes) -> OcrResult:
        self.calls += 1
        return OcrResult(boxes=[TextBox(text=text, bbox=bbox) for text, bbox in self._lines])
