"""สั่งงานเตรียมรูปตามลำดับ: ตรวจคุณภาพ → ตัดขอบ → ดัดเอียง → ปรับความคมชัด

★ ลำดับนี้ไม่ได้สุ่มมา — แต่ละขั้นทำให้ขั้นถัดไปทำงานได้ดีขึ้น:
    1. ตรวจคุณภาพก่อน  — รูปที่ยังไงก็อ่านไม่ได้ ตีกลับตั้งแต่ต้น ไม่เปลืองแรงขั้นอื่น
    2. ตัดขอบ          — ทิ้งพื้นหลัง (โต๊ะ/มือ/เงา) ที่จะไปกวนการวัดมุมเอียงในขั้นถัดไป
    3. ดัดเอียง        — พอเหลือแต่ใบเสร็จแล้ว การวัดมุมของแถวตัวอักษรจึงแม่น
    4. ปรับความคมชัด    — ทำเป็นขั้นสุดท้ายกับพื้นที่ที่เหลือจริงๆ เท่านั้น

    (ถ้าปรับความคมชัดก่อนตัดขอบ = เสียแรงปรับพื้นที่ที่กำลังจะถูกทิ้ง
     และ contrast ของพื้นหลังจะไปดึงค่าเฉลี่ยจนใบเสร็จปรับได้ไม่ดี)

รับ/คืนเป็น bytes เพื่อให้ scan_job ไม่ต้องรู้จัก numpy/OpenCV เลย
"""
from __future__ import annotations

import cv2
import numpy as np

from app.image_prep.image_quality import assess_quality
from app.image_prep.opencv_crop import crop_receipt
from app.image_prep.opencv_deskew import deskew
from app.image_prep.opencv_enhance import enhance
from app.observability.logging import get_logger
from app.reliability.errors import InputValidationError

log = get_logger(__name__)

#: คุณภาพ JPEG ตอนเขียนกลับ — สูงพอไม่ให้ตัวเลขแตก แต่ไม่ใหญ่เกินจำเป็น
_OUTPUT_JPEG_QUALITY = 95

#: จำกัดด้านยาวสุดของรูปก่อนเข้า OCR — ★ กัน PaddleOCR แครช (segfault) กับรูปมือถือละเอียดสูง
#:
#: เจอจริงตอน deploy: รูปมือถือ 3059x4058 (12MP) ทำ paddle segfault ทันที
#: (log: "Resized image size (3059x4058) exceeds max_side_limit of 4000" แล้วดับ)
#: ใบเสร็จอ่านออกสบายที่ ~2560px — ย่อลงมากันแครช + เร็วขึ้น + ไม่เสียความแม่น
#: ★ ชุดเฉลย 28 ใบด้านยาวสุด 1477px จึง "ไม่ถูกแตะ" = ตัวเลขที่วัดไว้ไม่เปลี่ยน
_MAX_OCR_SIDE = 2560


def prepare_for_ocr(image_bytes: bytes) -> bytes:
    """เตรียมรูปให้พร้อมอ่าน · คุณภาพไม่ผ่าน → InputValidationError (บอกเหตุผลกับลูกค้า)"""
    image = _limit_size(_decode(image_bytes))

    report = assess_quality(image)
    if not report.acceptable:
        log.info(
            "รูปไม่ผ่านเกณฑ์คุณภาพ",
            extra={"blur": round(report.blur_score, 1), "brightness": round(report.brightness, 1)},
        )
        raise InputValidationError(report.reason or "รูปไม่ชัดพอ กรุณาถ่ายใหม่")

    # ★ ครอบเพดานอีกครั้งหลังตัดขอบ — การดัดมุมมอง (perspective warp) ขยายภาพกลับไป
    #   เกินเพดานได้ (เจอจริง: 2560 → 2762) ต้องกันให้ "รูปที่ส่งเข้า OCR" ไม่เกินแน่นอน
    prepared = _limit_size(enhance(deskew(crop_receipt(image))))

    log.info(
        "เตรียมรูปเสร็จ",
        extra={
            "blur": round(report.blur_score, 1),
            "size_before": f"{image.shape[1]}x{image.shape[0]}",
            "size_after": f"{prepared.shape[1]}x{prepared.shape[0]}",
        },
    )
    return _encode(prepared)


def _decode(image_bytes: bytes) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        # ผ่าน upload_check มาแล้วจึงไม่ควรเกิด — แต่กันไว้ไม่ให้ worker พังแบบไม่มีคำอธิบาย
        raise InputValidationError("อ่านไฟล์รูปไม่ได้ กรุณาถ่ายใหม่")
    return image


def _limit_size(image: np.ndarray) -> np.ndarray:
    """ย่อรูปถ้าด้านยาวเกินเพดาน — คงสัดส่วนเดิม · เล็กกว่าเพดานอยู่แล้วคืนรูปเดิมไม่แตะ

    ทำก่อนทุกขั้น: ตัดขอบ/ดัดเอียง/OCR ล้วนทำงานบนรูปที่ถูกจำกัดขนาดแล้ว
    → กัน paddle แครช และทุกขั้นเร็วขึ้นโดยไม่ต้องแก้ทีละที่
    """
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest <= _MAX_OCR_SIDE:
        return image
    scale = _MAX_OCR_SIDE / longest
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def _encode(image: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), _OUTPUT_JPEG_QUALITY])
    if not ok:
        raise InputValidationError("แปลงรูปไม่สำเร็จ กรุณาลองใหม่")
    return buffer.tobytes()
