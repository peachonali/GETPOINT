"""ตัวจริง: อ่านตัวอักษรด้วย PaddleOCR (implementation ของ OcrEngine)

★ ทำไม PaddleOCR: รันบนเครื่องเราเอง ไม่มีค่าใช้จ่ายต่อรูป ไม่ส่งใบเสร็จลูกค้าออกนอกระบบ
  (ต่างจาก cloud OCR ที่จ่ายทุกครั้งและต้องส่งข้อมูลออก — สำคัญเรื่อง PDPA)

★ โหลดโมเดลครั้งเดียวตอนสร้าง object ไม่ใช่ทุกครั้งที่อ่าน:
  โหลดโมเดลใช้เวลาหลายวินาที ถ้าทำทุกใบจะช้าจนหลุด SLO (< 15 วิ ต่อใบ)
  worker สร้างตัวนี้ครั้งเดียวตอนบูตแล้วใช้ซ้ำตลอด (ดู composition.py)

⚠ ตั้งค่าโดยเจตนา (แต่ละตัวมีเหตุผล):
    lang="th"                        รองรับไทย+อังกฤษที่ปนกันบนใบเสร็จไทย
    use_doc_orientation_classify=F   เราดัดภาพเองแล้วใน image_prep (เร็วกว่า/คุมได้)
    use_doc_unwarping=False          เราตัด+ดัดมุมมองเองแล้วใน opencv_crop
    use_textline_orientation=False   ใบเสร็จเป็นแนวนอนหมด ไม่ต้องเสียเวลาตรวจ
"""
from __future__ import annotations

import os
import threading
from typing import Any

# ★ ปิดการเช็คเน็ตตอนโหลดโมเดล — โมเดลถูกดาวน์โหลดไว้ในเครื่องแล้วตั้งแต่ติดตั้ง
#   ถ้าไม่ปิด PaddleOCR จะพยายามต่อเน็ตทุกครั้งที่บูต ทำให้:
#     - ช้าโดยไม่จำเป็น (และช้ามากถ้าเน็ตอืด)
#     - worker บูตไม่ขึ้นถ้าเซิร์ฟเวอร์ไม่มีเน็ตออกนอก (ซึ่งเป็นการตั้งค่าที่ปลอดภัยกว่า)
#   ต้องตั้งก่อน import paddleocr จึงวางไว้ระดับโมดูล ไม่ใช่ในฟังก์ชัน
os.environ.setdefault("DISABLE_MODEL_SOURCE_CHECK", "True")

import cv2
import numpy as np

from app.observability.logging import get_logger
from app.ocr.ocr_interface import OcrEngine
from app.ocr.ocr_result import OcrResult, TextBox
from app.reliability.errors import InputValidationError

log = get_logger(__name__)

DEFAULT_LANG = "th"

#: ตัดผลที่โมเดลไม่มั่นใจทิ้ง — ข้อความมั่วจะไปกวน field_extractor มากกว่าช่วย
DEFAULT_MIN_CONFIDENCE = 0.5


class PaddleOcr(OcrEngine):
    def __init__(
        self,
        *,
        lang: str = DEFAULT_LANG,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    ) -> None:
        self._lang = lang
        self._min_confidence = min_confidence
        self._engine: Any | None = None
        # โหลดโมเดลแบบ lazy + กันหลายเธรดโหลดพร้อมกัน (เปลืองแรมหลายเท่า)
        self._lock = threading.Lock()

    def read(self, image_bytes: bytes) -> OcrResult:
        """อ่านรูป → ข้อความ + ตำแหน่ง · เรียงจากบนลงล่างตามที่ตาคนอ่าน"""
        image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise InputValidationError("อ่านไฟล์รูปไม่ได้ กรุณาถ่ายใหม่")

        raw = self._get_engine().predict(image)
        boxes = self._to_text_boxes(raw)

        log.info("OCR อ่านเสร็จ", extra={"lines": len(boxes)})
        return OcrResult(boxes=boxes)

    def _get_engine(self) -> Any:
        if self._engine is None:
            with self._lock:
                if self._engine is None:  # เช็คซ้ำในล็อก — เธรดอื่นอาจโหลดเสร็จไปแล้ว
                    from paddleocr import PaddleOCR

                    log.info("กำลังโหลดโมเดล OCR (ครั้งเดียวต่อ process)")
                    self._engine = PaddleOCR(
                        lang=self._lang,
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=False,
                    )
        return self._engine

    def _to_text_boxes(self, raw: Any) -> list[TextBox]:
        """แปลงผลของ PaddleOCR เป็นรูปแบบกลางของเรา

        ★ ห่อไว้ที่นี่ที่เดียว: รูปแบบผลลัพธ์ของ PaddleOCR เปลี่ยนไปมาระหว่างเวอร์ชัน
          (2.x คืน list ซ้อน list, 3.x คืน dict) ถ้าปล่อยให้ชั้นอื่นแตะโดยตรง
          วันอัปเกรดจะต้องไล่แก้ทั้งระบบ
        """
        boxes: list[TextBox] = []

        for page in raw or []:
            texts = page.get("rec_texts") or []
            scores = page.get("rec_scores") or []
            polys = page.get("rec_polys") or page.get("dt_polys") or []

            for index, text in enumerate(texts):
                score = scores[index] if index < len(scores) else 1.0
                if not text or not text.strip() or score < self._min_confidence:
                    continue

                poly = polys[index] if index < len(polys) else None
                boxes.append(TextBox(text=text.strip(), bbox=_to_bbox(poly)))

        # เรียงบน→ล่าง แล้วซ้าย→ขวา ให้ลำดับตรงกับที่คนอ่านใบเสร็จ
        # (field_extractor พึ่งลำดับนี้ เช่น "บรรทัดแรก = ชื่อร้าน")
        boxes.sort(key=lambda box: (box.bbox[1], box.bbox[0]))
        return boxes


def _to_bbox(poly: Any) -> tuple[int, int, int, int]:
    """แปลงรูปหลายเหลี่ยม 4 จุดของ PaddleOCR เป็นกรอบสี่เหลี่ยม (x1, y1, x2, y2)"""
    if poly is None:
        return (0, 0, 0, 0)

    points = np.asarray(poly, dtype=np.float32).reshape(-1, 2)
    x1, y1 = points.min(axis=0)
    x2, y2 = points.max(axis=0)
    return (int(x1), int(y1), int(x2), int(y2))
