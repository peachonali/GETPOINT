"""ตรวจคุณภาพรูปก่อนเข้า OCR — เบลอ/มืดเกินไป ตีกลับให้ถ่ายใหม่ (fail fast)

★ ทำไมต้องตีกลับตั้งแต่ต้น:
    รูปเบลอ = OCR อ่านเลขผิด = ลูกค้าได้แต้มผิด ซึ่งเป็นความเสียหายที่แก้ยากที่สุด
    บอกให้ถ่ายใหม่ตั้งแต่ 2 วินาทีแรก ดีกว่าประมวลผลไป 15 วินาทีแล้วให้ผลที่เชื่อไม่ได้

    และประหยัด CPU ของ worker ไปกับรูปที่ยังไงก็อ่านไม่ได้

วิธีวัดความเบลอ: variance of Laplacian — ภาพชัดมี "ขอบ" เยอะ ค่าความแปรปรวนสูง
                 ภาพเบลอขอบเรียบหมด ค่าต่ำ (เป็นวิธีมาตรฐานที่เร็วและเชื่อถือได้)
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

#: ต่ำกว่านี้ = เบลอเกินอ่าน · ค่านี้ตั้งจากภาพทดสอบ ต้องปรับจริงเมื่อมี golden set
#: (ตั้งไว้ต่ำก่อนโดยตั้งใจ — ปฏิเสธผิดน่ารำคาญกว่าปล่อยผ่านแล้วอ่านพลาด)
BLUR_THRESHOLD = 60.0

#: ความสว่างเฉลี่ยที่ยอมรับได้ (0-255)
#:
#: ★ เพดานตั้งไว้สูงโดยตั้งใจ: ใบเสร็จคือ "กระดาษขาว" ถ่ายใกล้ๆ เต็มเฟรม
#:   ค่าเฉลี่ยย่อมสูง 200-250 เป็นเรื่องปกติ ไม่ใช่ความผิดปกติ
#:   (เคยตั้ง 240 แล้วตีกลับใบเสร็จที่ถ่ายมาดีๆ — เจอตอนเทส e2e)
#:   ส่วนรูปที่ "แสงจ้าจนอ่านไม่ออกจริงๆ" จะถูกจับด้วยเกณฑ์ความชัดอยู่แล้ว
#:   เพราะไม่มีขอบตัวอักษรเหลือให้วัด
MIN_BRIGHTNESS = 40.0
MAX_BRIGHTNESS = 252.0


@dataclass(frozen=True)
class QualityReport:
    """ผลตรวจ + เหตุผลที่คนอ่านรู้เรื่อง (ส่งต่อให้ลูกค้าได้เลย)"""

    acceptable: bool
    blur_score: float
    brightness: float
    reason: str | None = None


def assess_quality(image: np.ndarray) -> QualityReport:
    """ตรวจว่ารูปนี้พอจะอ่านได้ไหม"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image

    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(np.mean(gray))

    # ★ เช็คความสว่างก่อนความเบลอโดยตั้งใจ:
    #   รูปมืดจะวัดความชัดได้ต่ำไปด้วยเสมอ (ไม่มีแสงก็ไม่มีขอบให้วัด)
    #   ถ้าเช็คเบลอก่อน ลูกค้าที่ถ่ายในที่มืดจะได้คำแนะนำผิดว่า "ถ่ายให้ชัดขึ้น"
    #   ทั้งที่สิ่งที่ต้องแก้จริงคือ "ไปที่สว่างกว่านี้" — บอกต้นเหตุ ไม่ใช่บอกอาการ
    if brightness < MIN_BRIGHTNESS:
        return QualityReport(False, blur_score, brightness, "รูปมืดเกินไป กรุณาถ่ายในที่สว่างขึ้น")

    if brightness > MAX_BRIGHTNESS:
        return QualityReport(False, blur_score, brightness, "รูปสว่างจ้าเกินไป กรุณาเลี่ยงแสงสะท้อน")

    if blur_score < BLUR_THRESHOLD:
        return QualityReport(False, blur_score, brightness, "รูปเบลอเกินไป กรุณาถ่ายใหม่ให้ชัดขึ้น")

    return QualityReport(True, blur_score, brightness)
