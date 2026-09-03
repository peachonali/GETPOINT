"""ปรับความคมชัด + ลด noise ให้ OCR อ่านง่ายขึ้น

บริบทของใบเสร็จไทย (ทำไมต้องปรับแบบนี้):
    ส่วนใหญ่เป็นกระดาษความร้อน (thermal) → หมึกจางลงตามเวลา/ความร้อน
    ถ่ายด้วยมือถือ → มีเงามือ แสงไม่สม่ำเสมอ ด้านหนึ่งสว่างอีกด้านมืด

    ★ CLAHE (ปรับ contrast แบบแยกโซน) จึงเหมาะกว่าการปรับทั้งภาพพร้อมกัน
      เพราะมันดึงรายละเอียดในโซนมืดขึ้นมาโดยไม่ทำให้โซนสว่างไหม้

⚠ จงใจ "ไม่" แปลงเป็นขาวดำล้วน (binarize):
  PaddleOCR รุ่นใหม่เทรนมากับภาพระดับเทา/สี — บังคับเป็นขาวดำมักทำให้แย่ลง
  โดยเฉพาะกับหมึกจางที่จะหายไปทั้งตัวอักษร
"""
from __future__ import annotations

import cv2
import numpy as np

#: เพดานการดึง contrast — สูงไปจะดึง noise ขึ้นมาด้วยจนเป็นจุดๆ
_CLAHE_CLIP_LIMIT = 2.0

#: ขนาดโซนที่ CLAHE ทำงานทีละส่วน (8x8 เป็นค่ามาตรฐานที่ใช้ได้ดีกับเอกสาร)
_CLAHE_GRID = (8, 8)

#: ลด noise แบบรักษาขอบตัวอักษร — ค่าสูงไปตัวอักษรจะเบลอจนอ่านไม่ออก
_BILATERAL_DIAMETER = 5
_BILATERAL_SIGMA = 50


def enhance(image: np.ndarray) -> np.ndarray:
    """คืนภาพระดับเทาที่ contrast ดีขึ้นและ noise น้อยลง (พร้อมส่งเข้า OCR)"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image

    # 1) ลด noise ก่อน — ทำหลัง CLAHE จะเป็นการเบลอ noise ที่ถูกขยายแล้ว (สายเกินไป)
    denoised = cv2.bilateralFilter(
        gray, _BILATERAL_DIAMETER, _BILATERAL_SIGMA, _BILATERAL_SIGMA
    )

    # 2) ดึง contrast แบบแยกโซน — แก้ปัญหาเงาทับครึ่งใบ
    clahe = cv2.createCLAHE(clipLimit=_CLAHE_CLIP_LIMIT, tileGridSize=_CLAHE_GRID)
    return clahe.apply(denoised)
