"""อ่านใบเสร็จ 1 ใบด้วยระบบจริง แล้วคืนผลเป็น dict — แกนกลางของเครื่องมือฝึก OCR

★ ใช้ "ของจริงทั้งเส้น" ที่เดียวกับตอนสแกนจริง (image_prep → PaddleOCR → แยกค่า)
  ต่างกันแค่ปลายทาง: ตัวนี้คืนผลกลับมาให้ดู/ทำ Excel แทนที่จะส่งเข้า loga/LINE
  → สิ่งที่เห็นในเครื่องมือนี้ = สิ่งที่ระบบจริงอ่านได้เป๊ะ (ไม่ใช่การจำลอง)

★ โหลดโมเดล OCR ครั้งเดียว ใช้ซ้ำทุกใบ (โหลดใหม่ทุกใบจะช้ามาก)
  โหลดแบบ lazy — ตอน import ไฟล์นี้ยังไม่โหลด เพื่อให้เทส/สคริปต์อื่น import ได้เร็ว
"""
from __future__ import annotations

import threading
from typing import Any

from app.image_prep.image_pipeline import prepare_for_ocr
from app.receipt_data.field_extractor import extract_receipt_fields
from app.receipt_data.line_items import find_line_items
from app.reliability.errors import GetpointError

#: OCR ตัวเดียวของทั้งเครื่องมือ + lock กันโหลดซ้อนตอนหลายคำขอมาพร้อมกัน
_ocr_lock = threading.Lock()
_ocr = None


def _get_ocr():
    """คืน PaddleOcr ตัวเดิมเสมอ · โหลดครั้งแรกครั้งเดียว (ช้า ~20 วิ)"""
    global _ocr
    if _ocr is None:
        with _ocr_lock:
            if _ocr is None:  # เช็คซ้ำใต้ lock กันสองคำขอโหลดพร้อมกัน
                from app.ocr.paddle_ocr import PaddleOcr

                _ocr = PaddleOcr()
    return _ocr


def extract_one(filename: str, image: bytes) -> dict[str, Any]:
    """อ่านใบเสร็จ 1 ใบ → dict ที่พร้อมเอาไปแสดง/ลง Excel

    ★ ไม่โยน error ออก — อ่านไม่ได้ก็คืนแถวที่มี ok=False + เหตุผล
      เพราะเครื่องมือฝึกต้องเห็น "ใบที่อ่านไม่ได้" ด้วย (นั่นแหละคือใบที่ต้องเอาไปปรับ)

    คืน raw_text (ข้อความ OCR ดิบ) มาด้วยเสมอ — ให้คนดูได้ว่า "อ่านตัวอักษรมาว่าไง"
    แยกจาก "ตีความได้ว่าไง" (ยอด/ร้าน/วันที่)
    """
    ocr = _get_ocr()

    try:
        result = ocr.read(prepare_for_ocr(image))
    except GetpointError as exc:
        # รูปถูกตีกลับตั้งแต่ขั้นเตรียม (เบลอ/มืดเกิน) — เป็นคำตอบที่ยอมรับได้
        return _failed_row(filename, reason=str(exc), raw_lines=[])
    except Exception as exc:  # noqa: BLE001 — เครื่องมือต้องไม่ล้มเพราะใบเดียว
        return _failed_row(filename, reason=f"{type(exc).__name__}: {exc}", raw_lines=[])

    raw_lines = result.lines()

    try:
        fields = extract_receipt_fields(result)
    except GetpointError as exc:
        return _failed_row(filename, reason=str(exc), raw_lines=raw_lines)

    items = fields["items"]
    return {
        "filename": filename,
        "ok": True,
        "reason": "",
        "merchant": fields["merchant"],
        "merchant_code": fields["merchant_code"] or "",
        "total_amount": fields["total_amount"],
        "receipt_date": fields["receipt_date"].isoformat() if fields["receipt_date"] else "",
        "receipt_time": fields["receipt_time"].strftime("%H:%M") if fields["receipt_time"] else "",
        "reference_codes": ", ".join(fields["reference_codes"]),
        "items": "; ".join(_format_item(it) for it in items),
        "raw_text": "\n".join(raw_lines),
    }


def _format_item(item) -> str:
    """ชื่อสินค้า + ราคา (ถ้ามี) → ข้อความสั้นๆ สำหรับช่อง Excel"""
    return f"{item.name} = {item.price:.0f}" if item.price is not None else item.name


def _failed_row(filename: str, *, reason: str, raw_lines: list[str]) -> dict[str, Any]:
    return {
        "filename": filename,
        "ok": False,
        "reason": reason,
        "merchant": "",
        "merchant_code": "",
        "total_amount": None,
        "receipt_date": "",
        "receipt_time": "",
        "reference_codes": "",
        "items": "",
        "raw_text": "\n".join(raw_lines),
    }
