"""หาขอบใบเสร็จในรูปถ่าย แล้วตัดพื้นหลังทิ้ง + ดัดมุมมองให้ตรง

★ ทำไมนี่คือขั้นที่คุ้มที่สุดขั้นหนึ่ง:
    ลูกค้าถ่ายใบเสร็จวางบนโต๊ะ → ในรูปมีทั้งโต๊ะ มือ เงา ของรอบข้าง
    ถ้าโยนทั้งรูปให้ OCR มันจะพยายามอ่านลายไม้โต๊ะด้วย แล้วสับสน
    ตัดให้เหลือแต่ใบเสร็จ = ลดสิ่งรบกวนทั้งหมดในขั้นตอนเดียว

    และเพราะคนถ่ายจากมุมเอียง (ใบเสร็จเป็นสี่เหลี่ยมคางหมูในรูป) เราจึง "ดัดมุมมอง"
    (perspective transform) ให้กลับเป็นสี่เหลี่ยมผืนผ้าตรงๆ เหมือนสแกนเนอร์

⚠ ถ้าหาขอบไม่เจอ (ใบเสร็จเต็มเฟรม/พื้นหลังกลืน) จะคืนรูปเดิม ไม่ใช่พัง
  เพราะรูปเดิมยังอ่านได้ ดีกว่าตัดมั่วแล้วเสียส่วนที่มียอดเงิน
"""
from __future__ import annotations

import cv2
import numpy as np

#: ย่อรูปก่อนหาขอบ — เร็วขึ้นมากและผลไม่ต่าง (หาขอบไม่ต้องใช้ความละเอียดสูง)
_DETECT_WIDTH = 800

#: ผู้สมัครต้องมีพื้นที่อย่างน้อยเท่านี้ของรูป — กันไปจับกรอบเล็กๆ ในรูป (โลโก้/ตราประทับ)
_MIN_AREA_RATIO = 0.25

#: ความคลาดเคลื่อนที่ยอมให้ตอนลดรูปเส้นขอบเป็นสี่เหลี่ยม (ยิ่งมากยิ่งหยาบ)
_APPROX_EPSILON_RATIO = 0.02

_QUAD_CORNERS = 4


def crop_receipt(image: np.ndarray) -> np.ndarray:
    """ตัดเฉพาะใบเสร็จออกมา + ดัดให้ตรง · หาขอบไม่เจอ → คืนรูปเดิม"""
    quad = _find_receipt_quad(image)
    if quad is None:
        return image
    return _warp_to_rectangle(image, quad)


def _find_receipt_quad(image: np.ndarray) -> np.ndarray | None:
    """หาสี่เหลี่ยมที่น่าจะเป็นใบเสร็จ · คืนพิกัด 4 มุมในสเกลของรูปจริง"""
    height, width = image.shape[:2]
    scale = _DETECT_WIDTH / width if width > _DETECT_WIDTH else 1.0
    small = cv2.resize(image, None, fx=scale, fy=scale) if scale != 1.0 else image

    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
    # เบลอเล็กน้อยก่อนหาขอบ — กันลายพื้นผิว/noise กลายเป็น "ขอบ" ปลอม
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    # ต่อเส้นขอบที่ขาดเป็นช่วงๆ ให้ติดกัน (ขอบใบเสร็จมักขาดตรงที่แสงจ้า)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    small_area = small.shape[0] * small.shape[1]
    # ไล่จากรูปร่างใหญ่สุดก่อน — ใบเสร็จควรเป็นวัตถุเด่นที่สุดในรูป
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        if cv2.contourArea(contour) < small_area * _MIN_AREA_RATIO:
            break  # เล็กเกินไปแล้ว ตัวถัดไปยิ่งเล็ก ไม่ต้องดูต่อ

        perimeter = cv2.arcLength(contour, closed=True)
        approx = cv2.approxPolyDP(contour, _APPROX_EPSILON_RATIO * perimeter, closed=True)
        if len(approx) == _QUAD_CORNERS:
            return approx.reshape(4, 2).astype(np.float32) / scale

    return None


def _warp_to_rectangle(image: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """ดัดสี่เหลี่ยมคางหมู (ถ่ายเอียง) ให้กลับเป็นสี่เหลี่ยมผืนผ้าตรง"""
    ordered = _order_corners(quad)
    top_left, top_right, bottom_right, bottom_left = ordered

    # ขนาดปลายทาง = ด้านที่ยาวที่สุดของแต่ละคู่ (กันข้อมูลถูกบีบหาย)
    width = int(max(np.linalg.norm(top_right - top_left), np.linalg.norm(bottom_right - bottom_left)))
    height = int(max(np.linalg.norm(bottom_left - top_left), np.linalg.norm(bottom_right - top_right)))
    if width < 1 or height < 1:
        return image

    destination = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32
    )
    matrix = cv2.getPerspectiveTransform(ordered, destination)
    return cv2.warpPerspective(image, matrix, (width, height))


def _order_corners(quad: np.ndarray) -> np.ndarray:
    """เรียง 4 มุมให้เป็น ซ้ายบน → ขวาบน → ขวาล่าง → ซ้ายล่าง เสมอ

    จำเป็นเพราะ findContours คืนมุมมาแบบไม่รับประกันลำดับ ถ้าไม่เรียงก่อน
    ภาพที่ดัดออกมาจะพลิกหัวกลับหางหรือกลับด้านซ้ายขวา
    """
    ordered = np.zeros((4, 2), dtype=np.float32)
    total = quad.sum(axis=1)          # x+y น้อยสุด = ซ้ายบน, มากสุด = ขวาล่าง
    diff = np.diff(quad, axis=1)      # x-y น้อยสุด = ขวาบน, มากสุด = ซ้ายล่าง

    ordered[0] = quad[np.argmin(total)]
    ordered[2] = quad[np.argmax(total)]
    ordered[1] = quad[np.argmin(diff)]
    ordered[3] = quad[np.argmax(diff)]
    return ordered
