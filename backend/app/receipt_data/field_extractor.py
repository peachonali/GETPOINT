"""ดึงค่าจากข้อความ OCR มายัดลงโครงกลาง (Receipt)

⚠ นี่คือเวอร์ชัน Step 3 — เป็น "ตัวอ่านแบบเดาจากคำสำคัญ" ที่ใช้ได้กับใบเสร็จทั่วไป
  Step 5 จะถูกแทนที่ด้วย template_matcher ซึ่งรู้ว่าแต่ละร้านวางค่าไว้ตรงไหน (แม่นกว่ามาก)
  ตอนนี้มีไว้เพื่อให้ต่อเส้นทั้งสายได้ก่อน ตามหลัก walking skeleton

★ กฎที่ยึดไว้ตั้งแต่ตอนนี้: อ่านยอดไม่ได้ = ล้มเหลว ห้ามเดา
  ให้แต้มผิดเสียหายกว่าไม่ให้แต้ม (ลูกค้าถ่ายใหม่ได้ แต่แต้มที่ให้ผิดไปแล้วดึงคืนยาก)
"""
from __future__ import annotations

import re
from datetime import date, datetime

from app.ocr.ocr_result import OcrResult
from app.reliability.errors import InputValidationError

#: คำที่มักนำหน้า "ยอดรวมสุดท้าย" บนใบเสร็จไทย/อังกฤษ
#: เรียงจากเจาะจงที่สุดไปทั่วไปที่สุด — "รวมทั้งสิ้น" ชนะ "รวม" เสมอ
_TOTAL_KEYWORDS = (
    "รวมทั้งสิ้น", "ยอดสุทธิ", "ยอดรวมสุทธิ", "จำนวนเงินรวม",
    "grand total", "net total", "total amount", "ยอดรวม", "total",
)

#: คำนำหน้าเลขที่ใบเสร็จ
_RECEIPT_NO_KEYWORDS = ("เลขที่", "เลขที่ใบเสร็จ", "receipt no", "invoice no", "no.", "bill no")

#: ตัวเลขเงิน: 1,234.56 หรือ 250.00 หรือ 250
_AMOUNT_PATTERN = re.compile(r"(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)")

#: วันที่รูปแบบที่พบบ่อย — d/m/Y, d-m-Y (รองรับปี 2 และ 4 หลัก)
_DATE_PATTERN = re.compile(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})")

#: ปีไทย (พ.ศ.) มากกว่าปีสากลอยู่ 543 — ใบเสร็จไทยใช้ พ.ศ. กันเยอะ
_BUDDHIST_YEAR_OFFSET = 543
_BUDDHIST_YEAR_THRESHOLD = 2400  # ปีเกินนี้ถือว่าเป็น พ.ศ.


def extract_receipt_fields(ocr: OcrResult) -> dict:
    """อ่าน OcrResult → dict ของ field กลาง · อ่านยอดไม่ได้ → InputValidationError

    คืน dict (ไม่ใช่ Receipt) เพราะยังขาด field ที่มาจากที่อื่น (tenant_id, source_image_id)
    ผู้เรียก (scan_job) เป็นคนประกอบ Receipt ให้ครบ
    """
    lines = [box.text.strip() for box in ocr.boxes if box.text.strip()]

    total = _find_total(lines)
    if total is None:
        raise InputValidationError("อ่านยอดเงินจากใบเสร็จไม่ได้ กรุณาถ่ายให้ชัดขึ้น")

    return {
        "merchant": lines[0] if lines else "ไม่ทราบร้าน",  # บรรทัดแรกมักเป็นชื่อร้าน
        "receipt_no": _find_receipt_no(lines),
        "receipt_date": _find_date(lines),  # ชื่อตรงกับ Receipt.receipt_date
        "total_amount": total,
    }


def _find_total(lines: list[str]) -> float | None:
    """หายอดรวมจากบรรทัดที่มีคำสำคัญ · ไม่เจอคำสำคัญเลย → None (ไม่เดาจากเลขที่ใหญ่สุด)"""
    for keyword in _TOTAL_KEYWORDS:
        for line in lines:
            if keyword in line.lower() or keyword in line:
                amount = _last_amount_in(line)
                if amount is not None:
                    return amount
    return None


def _last_amount_in(line: str) -> float | None:
    """เอาตัวเลขเงิน "ตัวสุดท้าย" ของบรรทัด

    เพราะบรรทัดแบบ "ภาษีมูลค่าเพิ่ม 7% 16.36" มีเลข 7 นำหน้า ตัวที่เป็นเงินคือตัวท้าย
    """
    matches = _AMOUNT_PATTERN.findall(line)
    if not matches:
        return None
    try:
        return float(matches[-1].replace(",", ""))
    except ValueError:
        return None


def _find_receipt_no(lines: list[str]) -> str | None:
    for line in lines:
        lowered = line.lower()
        for keyword in _RECEIPT_NO_KEYWORDS:
            if keyword in lowered or keyword in line:
                # เอาส่วนหลังคำสำคัญ แล้วตัดช่องว่าง/เครื่องหมายหัวท้ายทิ้ง
                index = lowered.find(keyword) if keyword in lowered else line.find(keyword)
                candidate = line[index + len(keyword):].strip(" :：#-")
                if candidate:
                    return candidate.split()[0]
    return None


def _find_date(lines: list[str]) -> date | None:
    for line in lines:
        match = _DATE_PATTERN.search(line)
        if not match:
            continue

        day, month, year = (int(part) for part in match.groups())
        if year < 100:
            year += 2000            # 26 → 2026
        if year > _BUDDHIST_YEAR_THRESHOLD:
            year -= _BUDDHIST_YEAR_OFFSET  # 2569 (พ.ศ.) → 2026

        try:
            return datetime(year, month, day).date()
        except ValueError:
            continue  # เลขวัน/เดือนเพี้ยน (OCR อ่านผิด) — ลองบรรทัดถัดไป
    return None
