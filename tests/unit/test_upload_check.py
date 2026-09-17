"""เทส app/security/upload_check.py — ด่านแรกที่รับไฟล์จากลูกค้า

สร้างรูปจริงด้วย Pillow แทนการ mock — เพราะสิ่งที่เทสคือ "พฤติกรรมกับไฟล์จริง"
(magic bytes, decode, EXIF) ถ้า mock ก็ไม่ได้เทสอะไรเลย
"""
import io

import pytest
from PIL import Image

from app.reliability.errors import InputValidationError
from app.security.upload_check import (
    MAX_UPLOAD_BYTES,
    check_and_clean_image,
    detect_image_format,
)


#: EXIF tag ที่มือถือฝังมากับรูปถ่าย (ค่าตามมาตรฐาน EXIF)
_TAG_MAKE = 0x010F
_TAG_MODEL = 0x0110
_TAG_GPS_IFD = 0x8825
_GPS_LATITUDE_REF = 1
_GPS_LATITUDE = 2


def _image_bytes(fmt="JPEG", size=(800, 1200), with_exif=False) -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGB", size, color=(240, 235, 250))

    if with_exif:
        exif = image.getexif()
        exif[_TAG_MAKE] = "Apple"
        exif[_TAG_MODEL] = "iPhone 15"
        gps = exif.get_ifd(_TAG_GPS_IFD)
        gps[_GPS_LATITUDE_REF] = "N"
        gps[_GPS_LATITUDE] = (13.0, 45.0, 0.0)  # พิกัดกรุงเทพ (องศา/ลิปดา/พิลิปดา)
        image.save(buffer, format=fmt, exif=exif)
    else:
        image.save(buffer, format=fmt)

    return buffer.getvalue()


def _read_exif(data: bytes):
    with Image.open(io.BytesIO(data)) as image:
        exif = image.getexif()
        return dict(exif), dict(exif.get_ifd(_TAG_GPS_IFD))


# ═══════════════════════════════════════════
# magic bytes — เชื่อไบต์จริง ไม่เชื่อนามสกุล
# ═══════════════════════════════════════════

def test_detects_jpeg_and_png():
    assert detect_image_format(_image_bytes("JPEG")) == "JPEG"
    assert detect_image_format(_image_bytes("PNG")) == "PNG"


def test_rejects_non_image_disguised_as_image():
    """ไฟล์ชื่อ .jpg แต่ข้างในเป็นสคริปต์ — ช่องโจมตีคลาสสิก ต้องไม่ผ่าน"""
    with pytest.raises(InputValidationError):
        check_and_clean_image(b"#!/bin/sh\nrm -rf /\n")


def test_rejects_empty_upload():
    with pytest.raises(InputValidationError):
        check_and_clean_image(b"")


def test_rejects_corrupt_image_with_valid_header():
    """หัวไฟล์ปลอมเป็น JPEG แต่ข้างในพัง — magic bytes อย่างเดียวจับไม่ได้
    ต้อง decode จริงถึงจะรู้"""
    with pytest.raises(InputValidationError):
        check_and_clean_image(b"\xff\xd8\xff" + b"\x00" * 500)


# ═══════════════════════════════════════════
# ขนาด
# ═══════════════════════════════════════════

def test_rejects_oversized_file():
    with pytest.raises(InputValidationError):
        check_and_clean_image(b"\xff\xd8\xff" + b"\x00" * MAX_UPLOAD_BYTES)


def test_rejects_too_small_image():
    """รูปเล็กเกินอ่านใบเสร็จไม่ออก — ตีกลับตั้งแต่ประตู ไม่เปลือง worker"""
    with pytest.raises(InputValidationError):
        check_and_clean_image(_image_bytes(size=(100, 100)))


def test_accepts_normal_phone_photo():
    assert check_and_clean_image(_image_bytes(size=(1080, 1920)))


# ═══════════════════════════════════════════
# ★ EXIF — PDPA
# ═══════════════════════════════════════════

def test_strips_gps_and_device_metadata():
    """รูปจากมือถือฝัง GPS + รุ่นเครื่องมาด้วย = ข้อมูลส่วนบุคคลเกินจำเป็น
    ต้องถูกล้างทิ้งตั้งแต่ประตู (CONTEXT ข้อ 3 — PDPA)"""
    original = _image_bytes(with_exif=True)
    original_exif, original_gps = _read_exif(original)
    assert original_gps, "ตั้งต้นต้องมี GPS จริงก่อน ไม่งั้นเทสไม่มีความหมาย"
    assert original_exif.get(_TAG_MAKE) == "Apple"

    cleaned_exif, cleaned_gps = _read_exif(check_and_clean_image(original))

    assert not cleaned_gps, "พิกัด GPS ต้องถูกลบ"
    assert _TAG_MAKE not in cleaned_exif, "ยี่ห้อเครื่องต้องถูกลบ"
    assert _TAG_MODEL not in cleaned_exif, "รุ่นเครื่องต้องถูกลบ"


def test_cleaned_image_is_still_readable():
    """ล้างแล้วต้องยังเป็นรูปที่เปิดได้และขนาดเท่าเดิม (ไม่ใช่ล้างจนพัง)"""
    cleaned = check_and_clean_image(_image_bytes(size=(800, 1200)))
    with Image.open(io.BytesIO(cleaned)) as image:
        assert image.size == (800, 1200)
        assert image.mode == "RGB"


def test_png_is_converted_to_jpeg():
    """แปลงเป็นรูปแบบเดียวตั้งแต่ประตู — ชั้นถัดไป (OpenCV/OCR) ไม่ต้องเดารูปแบบ"""
    assert detect_image_format(check_and_clean_image(_image_bytes("PNG"))) == "JPEG"


# ═══════════════════════════════════════════
# ★ EXIF orientation — ต้นเหตุ "รูปมือถืออ่านไม่ได้"
# ═══════════════════════════════════════════

_TAG_ORIENTATION = 0x0112


def _phone_portrait_photo() -> bytes:
    """จำลอง "รูปที่มือถือถือแนวตั้งถ่าย" เป๊ะแบบที่เครื่องเก็บจริง:

    ภาพตั้งตรง = แถบแดงอยู่ "บนสุด" · แต่เซ็นเซอร์เก็บพิกเซลตะแคง (หมุน 90° CCW)
    แล้วฝากแท็ก orientation=6 ไว้บอก viewer ว่า "หมุนตามเข็ม 90° ก่อนแสดง"
    → ถ้าลบแท็กทิ้งเฉยๆ โดยไม่หมุน ภาพจะตะแคง (แถบแดงไปอยู่ด้านข้าง)
    """
    upright = Image.new("RGB", (800, 1200), color=(245, 245, 245))
    for y in range(400):  # แถบแดงครอบ 1 ใน 3 ส่วนบน = จุดสังเกตทิศทาง
        for x in range(800):
            upright.putpixel((x, y), (220, 30, 30))

    sideways = upright.transpose(Image.ROTATE_90)  # เก็บพิกเซลตะแคง (CCW)
    exif = sideways.getexif()
    exif[_TAG_ORIENTATION] = 6
    buffer = io.BytesIO()
    sideways.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def test_applies_exif_orientation_so_photo_is_upright():
    """★ รูปมือถือแนวตั้ง (พิกเซลตะแคง + แท็ก orientation=6) ต้องถูกหมุนให้ตั้งตรง
    ก่อนลบ EXIF — ไม่งั้น OCR เจอตัวอักษรตะแคงแล้วอ่านไม่ออก (บั๊กที่ทำให้ "อ่านไม่ได้")

    ยืนยัน "ทิศถูก" ด้วยตำแหน่งแถบแดง ไม่ใช่แค่ขนาด — กันการหมุนผิดทางแล้วผ่านเทส
    """
    cleaned = check_and_clean_image(_phone_portrait_photo())

    with Image.open(io.BytesIO(cleaned)) as image:
        assert image.size == (800, 1200), "ต้องกลับมาเป็นแนวตั้ง (กว้าง<สูง)"
        top_red = image.getpixel((400, 60))
        bottom_gray = image.getpixel((400, 1140))

    assert top_red[0] > 150 and top_red[1] < 120, f"แถบแดงต้องอยู่บนสุด ได้ {top_red}"
    assert bottom_gray[0] > 150 and bottom_gray[1] > 150, f"ด้านล่างต้องเป็นพื้นเทา ได้ {bottom_gray}"


def test_upright_image_not_rotated():
    """รูปที่ตั้งตรงอยู่แล้ว (ไม่มีแท็ก orientation) ต้องไม่ถูกหมุน — กันแก้เกินจนพังของที่ดีอยู่"""
    cleaned = check_and_clean_image(_image_bytes(size=(800, 1200)))
    with Image.open(io.BytesIO(cleaned)) as image:
        assert image.size == (800, 1200)
