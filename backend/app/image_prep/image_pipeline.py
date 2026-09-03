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


def prepare_for_ocr(image_bytes: bytes) -> bytes:
    """เตรียมรูปให้พร้อมอ่าน · คุณภาพไม่ผ่าน → InputValidationError (บอกเหตุผลกับลูกค้า)"""
    image = _decode(image_bytes)

    report = assess_quality(image)
    if not report.acceptable:
        log.info(
            "รูปไม่ผ่านเกณฑ์คุณภาพ",
            extra={"blur": round(report.blur_score, 1), "brightness": round(report.brightness, 1)},
        )
        raise InputValidationError(report.reason or "รูปไม่ชัดพอ กรุณาถ่ายใหม่")

    prepared = enhance(deskew(crop_receipt(image)))

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


def _encode(image: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), _OUTPUT_JPEG_QUALITY])
    if not ok:
        raise InputValidationError("แปลงรูปไม่สำเร็จ กรุณาลองใหม่")
    return buffer.tobytes()
