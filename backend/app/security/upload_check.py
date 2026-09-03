"""ตรวจไฟล์ที่ลูกค้าอัปโหลด — ด่านแรกสุดที่รับของจากภายนอก

★ 3 หน้าที่ (ตาม CONTEXT ข้อ 3):
    1. เช็ก "ตัวไฟล์จริง" ด้วย magic bytes ไม่ใช่เชื่อนามสกุล/content-type ที่ลูกค้าส่งมา
       (ไฟล์ชื่อ .jpg แต่ข้างในเป็นสคริปต์ = ช่องโจมตีคลาสสิก)
    2. จำกัดขนาด — กันคนอัปไฟล์ใหญ่ถล่มดิสก์/แรม
    3. ★ ลบ EXIF — รูปถ่ายมือถือฝัง "พิกัด GPS + รุ่นเครื่อง + เวลา" มาด้วย
       เก็บไว้ = เก็บข้อมูลส่วนบุคคลเกินจำเป็น (PDPA) จึงล้างทิ้งตั้งแต่ประตู

คืนรูปที่ "ล้างแล้ว" ออกไป — ชั้นอื่นจะได้ใช้ของที่ปลอดภัยเสมอ ไม่ใช่ของดิบจากลูกค้า
"""
from __future__ import annotations

import io

from PIL import Image

from app.reliability.errors import InputValidationError

#: ยอมรับแค่ JPEG/PNG — ครอบคลุมทุกกล้องมือถือแล้ว และเป็นสองรูปแบบที่ OCR อ่านได้ดี
#: (ไม่รับ HEIC/WebP/GIF เพื่อลดพื้นที่โจมตีและ decoder ที่ต้องดูแล)
_MAGIC_SIGNATURES: dict[bytes, str] = {
    b"\xff\xd8\xff": "JPEG",
    b"\x89PNG\r\n\x1a\n": "PNG",
}

#: รูปจากมือถือหลังย่อฝั่ง frontend ~1-3 MB · 10 MB คือเผื่อคนอัปจากกล้องตรงๆ
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

#: กันรูปเล็กเกินจนอ่านไม่ออก (ดักไว้ก่อนเปลือง worker ไปทั้ง pipeline)
MIN_WIDTH = 200
MIN_HEIGHT = 200

#: กัน "decompression bomb" — ไฟล์เล็กแต่คลายออกมหาศาลจนกินแรมหมดเครื่อง
MAX_PIXELS = 50_000_000


def detect_image_format(data: bytes) -> str | None:
    """ดูจากไบต์จริงว่าเป็นไฟล์อะไร · ไม่ใช่รูปแบบที่รับได้ → None"""
    for signature, name in _MAGIC_SIGNATURES.items():
        if data.startswith(signature):
            return name
    return None


def check_and_clean_image(data: bytes) -> bytes:
    """ตรวจให้ครบทุกด่านแล้วคืนรูปที่ลบ EXIF แล้ว · ไม่ผ่าน → InputValidationError

    ข้อความ error เขียนให้ "ลูกค้าอ่านรู้เรื่องและแก้ได้" ไม่ใช่ศัพท์เทคนิค
    และไม่บอกรายละเอียดภายในระบบ (กันคนเอาไปหาช่องโจมตี)
    """
    if not data:
        raise InputValidationError("ไม่พบไฟล์รูป กรุณาถ่ายใหม่อีกครั้ง")

    if len(data) > MAX_UPLOAD_BYTES:
        limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise InputValidationError(f"ไฟล์ใหญ่เกิน {limit_mb} MB กรุณาถ่ายใหม่")

    if detect_image_format(data) is None:
        raise InputValidationError("รองรับเฉพาะรูปภาพ JPG หรือ PNG เท่านั้น")

    return _decode_verify_and_strip_exif(data)


def _decode_verify_and_strip_exif(data: bytes) -> bytes:
    """เปิดรูปจริงเพื่อยืนยันว่าไม่ใช่ไฟล์เสีย + เช็กขนาด + เขียนใหม่แบบไม่มี metadata

    ทำไมต้อง "เปิดจริง": magic bytes บอกแค่ 8 ไบต์แรก ไฟล์อาจปลอมหัวมาแล้วข้างในพัง
    ทำไม "เขียนใหม่": วิธีลบ EXIF ที่แน่นอนที่สุดคือสร้างไฟล์ใหม่จากพิกเซลล้วนๆ
    """
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()  # บังคับ decode จริง — ไฟล์เสียจะพังตรงนี้
            width, height = image.size

            if width * height > MAX_PIXELS:
                raise InputValidationError("รูปมีขนาดใหญ่เกินไป กรุณาถ่ายใหม่")

            if width < MIN_WIDTH or height < MIN_HEIGHT:
                raise InputValidationError("รูปเล็กเกินไป กรุณาถ่ายให้เห็นใบเสร็จชัดเจน")

            # แปลงเป็น RGB: ตัด alpha/palette ที่ JPEG ไม่รองรับ และทำให้ pipeline ถัดไป
            # เจอรูปแบบเดียวเสมอ (OpenCV/OCR ไม่ต้องเดา)
            cleaned = image.convert("RGB")

    except InputValidationError:
        raise
    except Exception as exc:
        # Pillow โยน error ได้หลายชนิดมากกับไฟล์เสีย — รวบเป็นข้อความเดียวที่ลูกค้าเข้าใจ
        raise InputValidationError("ไฟล์รูปเสียหรืออ่านไม่ได้ กรุณาถ่ายใหม่") from exc

    # เขียนใหม่จากพิกเซลล้วน → EXIF/GPS/comment หายหมดโดยธรรมชาติ
    output = io.BytesIO()
    cleaned.save(output, format="JPEG", quality=90)
    return output.getvalue()
