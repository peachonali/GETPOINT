"""อ่าน "จำนวนเงิน" จากข้อความ OCR — แยกออกมาเพราะเป็นจุดที่พลาดแล้วเสียหายที่สุด

★ ทุกกฎในไฟล์นี้มาจากการวัดกับใบเสร็จจริง ไม่ใช่การเดา:

    "17:25.14"   → ไม่ใช่เงิน เป็นเวลา    (เคยอ่านเป็น 25.14 บาท ทั้งที่ยอดจริง 528)
    "528-00"     → คือ 528.00              (เครื่องพิมพ์ความร้อนทำให้จุดกลายเป็นขีด)
    "2528,00"    → คือ 528.00              (฿ ถูกอ่านเป็น 2, จุดเป็นจุลภาค)
    "Tota114900" → ไม่ใช่เงิน               (ตัวเลขติดตัวอักษร = OCR อ่านเพี้ยน อย่าเดา)

หลักที่ยึด: ไม่มั่นใจ → คืน None ให้ระบบบอกลูกค้าว่า "ถ่ายใหม่"
            การเดาแล้วผิดแพงกว่าการยอมรับว่าอ่านไม่ได้
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: จำนวนเงินที่มี "ตัวคั่นทศนิยม" ชัดเจน — . , - ล้วนเป็นจุดทศนิยมที่ OCR อ่านเพี้ยนได้ทั้งนั้น
#: ต้องตามด้วยเลข 2 ตัวพอดี (สตางค์) เพื่อไม่ให้ไปจับ "12-3456" หรือวันที่
_DECIMAL_AMOUNT = re.compile(
    r"(?<![\w])(\d{1,3}(?:[,\s]\d{3})+|\d+)[.,\-](\d{2})(?![\d])"
)

#: ★ ตัวเลขที่ "จุลภาคตามด้วย 2 หลัก" — กำกวมและมักเป็น OCR อ่านตกหลัก
#:
#:   เจอจริงบนใบเสร็จ Pizza Company: ยอด "2,696" ถูกอ่านเป็น "2,69"
#:   ถ้าตีความว่าจุลภาคคือจุดทศนิยม จะได้ยอด 2.69 บาท ทั้งที่จริง 2,696 บาท
#:   (ผิดไป 1,000 เท่า — ลูกค้าจะได้แต้มแทบไม่มีเลย)
#:
#:   บนใบเสร็จไทย จุลภาคคือตัวคั่นหลักพัน ต้องตามด้วย 3 หลักเสมอ
#:   เจอแบบ 2 หลักเมื่อไหร่ = อ่านตก ให้ทิ้งไปเลย ไม่เดา
_TRUNCATED_THOUSANDS = re.compile(r"(?<![\w])\d{1,3},\d{2}(?![\d])")

#: จำนวนเต็มที่ยืนเดี่ยว (ไม่มีสตางค์) เช่น "Total 1,240"
_WHOLE_AMOUNT = re.compile(r"(?<![\w.,\-])(\d{1,3}(?:,\d{3})+|\d+)(?![\d.,\-])")

#: ★ เวลา — ต้องตัดทิ้งก่อนหาเงิน มิฉะนั้น "17:25.14" จะกลายเป็นยอด 25.14
#:   รูปแบบ HH:MM, HH:MM:SS, HH:MM.SS (บางเครื่องพิมพ์ใช้จุด)
_TIME_PATTERN = re.compile(r"\b\d{1,2}:\d{2}(?:[:.]\d{2})?\b")

#: วันที่ — 06/06/2026 หรือ 06-06-2569 · ตัดทิ้งเช่นกัน กันไปอ่านเป็นเงิน
_DATE_LIKE = re.compile(r"\b\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\b")

#: วันที่แบบมีชื่อเดือน — "Jun 6, 2026" (สลิปบัตรใช้รูปแบบนี้)
#: ถ้าไม่ตัด เลขปี 2026 จะถูกอ่านเป็นยอด 2,026 บาท
_DATE_WITH_MONTH = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{1,2}\s*,?\s*\d{2,4}\b",
    re.IGNORECASE,
)

#: คำนำหน้าสกุลเงินที่ "ติดกับตัวเลข" — เจอจริง "THB528.00" บนสลิปธนาคาร
#: ต้องแยกออกก่อน ไม่งั้นตัวเลขจะถูกมองว่าเป็นส่วนหนึ่งของคำ แล้วไม่ถูกอ่านเลย
_CURRENCY_PREFIX = re.compile(r"\b(thb|บาท|฿)(?=\d)", re.IGNORECASE)

#: รหัสยาวๆ (เลขใบกำกับ/บัตร/โทรศัพท์) — ยาวเกินกว่าจะเป็นยอดเงินใบเสร็จทั่วไป
_LONG_NUMBER = re.compile(r"\b\d{7,}\b")

#: ★ เลขที่ตามหลัง # หรือคำที่บอกว่าเป็น "รหัส" — ไม่ใช่เงินแน่นอน
#:   เจอจริงบนสลิปบัตร: "APPR.CODE#636282" เคยถูกอ่านเป็นยอด 636,282 บาท
#:   สลิปเต็มไปด้วยเลขพวกนี้ (TID, STAN, BATCH, TRACE, REF) ต้องกวาดออกให้หมด
_CODE_NUMBER = re.compile(
    r"(?:#\s*\d+"
    r"|\b(?:code|id|ref|no|tid|stan|batch|trace|inv|pos|reg|q)\b[#:.\s]*\d+)",
    re.IGNORECASE,
)

#: คำนำหน้าที่ยืนยันว่าเป็นเงินจริง — เจอแล้วมั่นใจขึ้นมาก
_CURRENCY_MARKERS = ("thb", "บาท", "฿")

#: ยอดที่เป็นไปได้ของใบเสร็จค้าปลีก — นอกช่วงนี้ถือว่าอ่านเพี้ยน
MIN_AMOUNT = 0.01
MAX_AMOUNT = 1_000_000.0


@dataclass(frozen=True)
class Amount:
    value: float
    #: มีตัวคั่นสตางค์ไหม (เช่น 250.00) — น่าเชื่อถือกว่าเลขจำนวนเต็มลอยๆ
    has_decimals: bool
    #: มีคำว่า THB/บาท/฿ อยู่ใกล้ๆ ไหม
    has_currency: bool

    @property
    def confidence(self) -> int:
        """คะแนนความน่าเชื่อถือ — ใช้เลือกเมื่อบรรทัดเดียวมีหลายตัวเลข"""
        return (2 if self.has_currency else 0) + (1 if self.has_decimals else 0)


def find_amounts(line: str) -> list[Amount]:
    """หาจำนวนเงินทั้งหมดในบรรทัด (เรียงตามที่ปรากฏ) · ไม่มี → list ว่าง"""
    cleaned = _strip_non_money(line)
    has_currency = any(marker in line.lower() for marker in _CURRENCY_MARKERS)

    amounts: list[Amount] = []

    for match in _DECIMAL_AMOUNT.finditer(cleaned):
        whole = re.sub(r"[,\s]", "", match.group(1))
        value = _to_float(f"{whole}.{match.group(2)}")
        if value is not None:
            amounts.append(Amount(value, has_decimals=True, has_currency=has_currency))

    # เลขจำนวนเต็มเก็บไว้ด้วย แต่จะถูกจัดอันดับต่ำกว่าเสมอ (ดู confidence)
    remaining = _DECIMAL_AMOUNT.sub(" ", cleaned)
    for match in _WHOLE_AMOUNT.finditer(remaining):
        value = _to_float(match.group(1).replace(",", ""))
        if value is not None:
            amounts.append(Amount(value, has_decimals=False, has_currency=has_currency))

    return amounts


def best_amount(line: str) -> float | None:
    """จำนวนเงินที่น่าเชื่อถือที่สุดในบรรทัด · ไม่มีเลย → None

    เลือกจาก "ความน่าเชื่อถือ" ก่อน แล้วค่อยเอาตัวขวาสุด
    (บนใบเสร็จ ยอดเงินอยู่ขวาสุดของบรรทัดเสมอ ส่วนซ้ายมักเป็นจำนวน/เปอร์เซ็นต์)
    """
    amounts = find_amounts(line)
    if not amounts:
        return None
    return max(amounts, key=lambda a: (a.confidence, amounts.index(a))).value


def _strip_non_money(line: str) -> str:
    """เตรียมบรรทัดก่อนหาเงิน — แยกสกุลเงินออกจากตัวเลข + ลบสิ่งที่ไม่ใช่เงิน"""
    # แยก "THB528.00" → "THB 528.00" ให้ตัวเลขยืนเดี่ยว (ทำก่อนลบอย่างอื่น)
    line = _CURRENCY_PREFIX.sub(r"\1 ", line)

    for pattern in (
        _TIME_PATTERN, _DATE_WITH_MONTH, _DATE_LIKE,
        _CODE_NUMBER, _LONG_NUMBER, _TRUNCATED_THOUSANDS,
    ):
        line = pattern.sub(" ", line)
    return line


def _to_float(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if MIN_AMOUNT <= value <= MAX_AMOUNT else None
