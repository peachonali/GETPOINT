"""ดัดภาพที่เอียงให้ตรง (deskew)

ทำไมสำคัญ: OCR อ่านตัวอักษรที่วางเป็นแนวนอนได้ดีที่สุด ถ้าใบเสร็จเอียง 5-10 องศา
ความแม่นตกลงชัดเจน — โดยเฉพาะตัวเลขที่อยู่ชิดกันอย่าง "1,250.00"

★ วิธีที่ใช้: projection profile (มาตรฐานของงาน document deskew)
    ลองหมุนภาพทีละองศาในช่วงที่เป็นไปได้ แล้วดูว่ามุมไหน "แถวตัวอักษรคมที่สุด"
    วัดด้วยการรวมหมึกในแต่ละแถวแนวนอน — ถ้าภาพตรง แถวที่มีตัวอักษรจะมีหมึกเยอะ
    แถวที่เป็นช่องว่างจะมีศูนย์ → ค่าต่างกันมาก (variance สูง)
    ถ้าภาพเอียง หมึกจะเกลี่ยข้ามแถว → ค่าใกล้กันหมด (variance ต่ำ)

    เคยลอง minAreaRect ของพิกเซลหมึก (วิธีที่เห็นบ่อยในตัวอย่างออนไลน์) แล้ว
    ให้ผลไม่น่าเชื่อถือ: วัดบางมุมไม่ได้เลย และบางมุมหมุนผิดทางจนเอียงกว่าเดิม
    (พิสูจน์ด้วยการทดลองจริงตอนเขียน — ดู tests/unit/test_image_prep.py)

⚠ แก้เฉพาะการเอียงเล็กน้อย (±15°) ซึ่งเป็นกรณีที่คนถือมือถือถ่ายจริง
  ไม่แก้รูปที่กลับหัว/ตะแคง 90° เพราะเสี่ยงเดาผิดแล้วทำให้แย่ลง
  (ถ้าเจอเคสนั้นบ่อยค่อยเพิ่มการตรวจทิศทางด้วย OCR ทีหลัง)
"""
from __future__ import annotations

import cv2
import numpy as np

#: มุมที่ยอมแก้ — เกินนี้ถือว่าวัดผิด ปล่อยไว้ดีกว่าหมุนมั่ว
_MAX_CORRECTION_DEGREES = 15.0

#: เอียงน้อยกว่านี้ไม่ต้องแก้ — หมุนรูปมีราคา (เบลอจาก interpolation) ไม่คุ้ม
_MIN_CORRECTION_DEGREES = 0.3


def deskew(image: np.ndarray) -> np.ndarray:
    """หมุนภาพให้แถวตัวอักษรเป็นแนวนอน · วัดมุมไม่ได้ → คืนรูปเดิม

    ทำสองจังหวะ:
        1. ตั้งลำตัวก่อน — ถ้ารูปถ่ายมาตะแคง 90° ให้หมุนเป็นแนวตั้งก่อน
        2. แล้วค่อยดัดมุมละเอียด ±15°
    """
    image = _fix_quarter_turn(image)

    angle = _estimate_skew_angle(image)
    if angle is None or abs(angle) < _MIN_CORRECTION_DEGREES:
        return image
    return _rotate(image, angle)


def _fix_quarter_turn(image: np.ndarray) -> np.ndarray:
    """หมุน 90° ถ้ารูปถ่ายมาตะแคง

    ★ ใบเสร็จเป็นกระดาษยาวแนวตั้งเสมอ ถ้ารูปออกมากว้างกว่าสูงมาก แปลว่าคนถ่ายตะแคง
      (เจอจริงในใบเสร็จที่เก็บมา — บางใบถ่ายหมุนเกือบ 90° ซึ่งเกินพิสัยของการดัดละเอียด
       ทำให้ OCR อ่านตัวอักษรแนวตั้งไม่ออกเลย)

    ⚠ ตัดสินจากสัดส่วนภาพเท่านั้น ไม่เดาจากเนื้อหา — ถ้าเดาผิดจะยิ่งแย่
      และไม่แก้กรณีกลับหัว 180° เพราะสัดส่วนบอกไม่ได้ (ต้องดูเนื้อหาซึ่งเสี่ยงกว่า)
    """
    height, width = image.shape[:2]
    if width <= height * _LANDSCAPE_RATIO:
        return image

    # หมุนทวนเข็มให้กลับเป็นแนวตั้ง — ถ้าเดาทางผิด ขั้นตอนวัดมุมละเอียดยังช่วยได้บ้าง
    return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)


#: กว้างเกินสูงกี่เท่าถึงถือว่า "ถ่ายตะแคง" — 1.3 เผื่อใบเสร็จสั้นๆ ที่ยังตั้งอยู่
_LANDSCAPE_RATIO = 1.3


#: ย่อภาพก่อนวัดมุม — ต้องหมุนหลายสิบรอบ ถ้าใช้ภาพเต็มจะช้าโดยไม่ได้ความแม่นเพิ่ม
_MEASURE_WIDTH = 600

#: ความละเอียดของการค้นหา — 0.5° พอสำหรับ OCR (ละเอียดกว่านี้ไม่ช่วยให้อ่านดีขึ้น)
_ANGLE_STEP_DEGREES = 0.5

#: ต้องมีหมึกอย่างน้อยเท่านี้ถึงจะวัดได้ (ภาพว่าง/มืดสนิทวัดไม่ได้)
_MIN_INK_PIXELS = 100


def _estimate_skew_angle(image: np.ndarray) -> float | None:
    """วัดว่าภาพเอียงกี่องศา · คืนค่าที่ "ส่งให้ _rotate ได้ตรงๆ" เพื่อดัดให้ตรง

    ลองทุกมุมในช่วง ±_MAX_CORRECTION_DEGREES แล้วเลือกมุมที่ทำให้แถวตัวอักษรคมที่สุด
    """
    binary = _ink_mask(image)
    if binary is None:
        return None

    best_angle, best_score = 0.0, _row_sharpness(binary)

    steps = int(_MAX_CORRECTION_DEGREES / _ANGLE_STEP_DEGREES)
    for step in range(-steps, steps + 1):
        angle = step * _ANGLE_STEP_DEGREES
        if angle == 0.0:
            continue

        score = _row_sharpness(_rotate_flat(binary, angle))
        if score > best_score:
            best_angle, best_score = angle, score

    return best_angle


def _ink_mask(image: np.ndarray) -> np.ndarray | None:
    """แยกหมึก (เข้ม) ออกจากกระดาษ (สว่าง) เป็นภาพขาวดำย่อส่วน"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image

    width = gray.shape[1]
    if width > _MEASURE_WIDTH:
        scale = _MEASURE_WIDTH / width
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    # THRESH_OTSU เลือกเกณฑ์ตัดเองตามความสว่างของรูปนั้น (ใบเสร็จแต่ละใบสว่างไม่เท่ากัน)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    return binary if int(np.count_nonzero(binary)) >= _MIN_INK_PIXELS else None


def _row_sharpness(binary: np.ndarray) -> float:
    """ยิ่งสูง = แถวตัวอักษรกับช่องว่างยิ่งแยกกันชัด = ภาพยิ่งตรง

    ใช้ผลต่างระหว่างแถวติดกัน (ไม่ใช่ variance เฉยๆ) เพราะมันไวต่อ "ขอบบน-ล่าง
    ของแถวตัวอักษร" ซึ่งคือสิ่งที่เบลอหายไปเมื่อภาพเอียง
    """
    row_ink = binary.sum(axis=1, dtype=np.float64)
    return float(np.abs(np.diff(row_ink)).sum())


def _rotate_flat(binary: np.ndarray, angle: float) -> np.ndarray:
    """หมุนภาพขาวดำโดยคงขนาดเดิม — ใช้ตอน "ลองมุม" เท่านั้น จึงเน้นเร็ว"""
    height, width = binary.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    return cv2.warpAffine(binary, matrix, (width, height), flags=cv2.INTER_NEAREST)


def _rotate(image: np.ndarray, angle: float) -> np.ndarray:
    """หมุนภาพรอบจุดกึ่งกลาง โดยขยายผืนผ้าใบไม่ให้มุมภาพถูกตัดหาย"""
    height, width = image.shape[:2]
    center = (width / 2, height / 2)
    matrix = cv2.getRotationMatrix2D(center, angle, scale=1.0)

    # คำนวณขนาดใหม่หลังหมุน เพื่อไม่ให้เนื้อหาที่มุมภาพหลุดออกนอกกรอบ
    cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
    new_width = int(height * sin + width * cos)
    new_height = int(height * cos + width * sin)
    matrix[0, 2] += new_width / 2 - center[0]
    matrix[1, 2] += new_height / 2 - center[1]

    return cv2.warpAffine(
        image, matrix, (new_width, new_height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,  # เติมขอบด้วยสีข้างเคียง ไม่ให้มีแถบดำหลอก OCR
    )
