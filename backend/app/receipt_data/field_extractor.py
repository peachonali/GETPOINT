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
from difflib import SequenceMatcher

from app.merchant.merchant_resolver import resolve
from app.merchant.template_rules import validate
from app.observability.logging import get_logger
from app.ocr.ocr_result import OcrResult
from app.receipt_data.amount_parser import best_amount
from app.receipt_data.datetime_parser import find_date, find_time
from app.receipt_data.line_items import find_line_items
from app.receipt_data.reference_code import find_reference_codes
from app.receipt_data.total_finder import find_total
from app.reliability.errors import InputValidationError

log = get_logger(__name__)

#: คำที่มักนำหน้า "ยอดรวมสุดท้าย" บนใบเสร็จไทย/อังกฤษ
#: เรียงจากเจาะจงที่สุด (คะแนนสูง) ไปทั่วไปที่สุด — "รวมทั้งสิ้น" ชนะ "total" เสมอ
_TOTAL_KEYWORDS = (
    "รวมทั้งสิ้น", "ยอดสุทธิ", "ยอดรวมสุทธิ", "จำนวนเงินรวม", "ยอดชำระ",
    "grand total", "net total", "total amount", "amount due", "balance due",
    "sale amount", "จำนวนเงิน", "รวมเงิน", "ยอดรวม", "total",
)

#: ★ บรรทัดที่มีคำพวกนี้ "ไม่ใช่" ยอดสุดท้าย แม้จะมีคำว่า total/รวม อยู่ก็ตาม
#:
#: เจอของจริงตอนทดสอบ: ระบบอ่าน "SUBTOTAL 233.64" มาเป็นยอดรวม เพราะคำว่า
#: "total" ซ่อนอยู่ใน "subtotal" → ลูกค้าจะได้แต้มจากยอดก่อน VAT (น้อยกว่าที่จ่ายจริง)
#: นี่คือความผิดพลาดแบบที่ไม่มีใครสังเกตจนกว่าจะมีคนทักท้วง
_NOT_FINAL_TOTAL = (
    "subtotal", "sub total", "sub-total",
    "ยอดก่อน", "ก่อนภาษี", "ไม่รวมภาษี", "ก่อนหักส่วนลด",
    "ส่วนลด", "discount", "change", "เงินทอน", "cash", "เงินสด",
)

#: คำนำหน้าเลขที่ใบเสร็จ
_RECEIPT_NO_KEYWORDS = ("เลขที่", "เลขที่ใบเสร็จ", "receipt no", "invoice no", "no.", "bill no")

#: ตัวเลขเงิน: 1,234.56 หรือ 250.00 หรือ 250
#:
#: ★ (?<![\w.]) และ (?![\d.]) สำคัญมาก — บังคับให้ตัวเลขต้อง "ยืนเดี่ยว" ไม่ใช่ชิ้นส่วน
#:   ของก้อนอักษรที่ OCR อ่านเพี้ยน
#:
#:   เจอของจริง: OCR อ่าน "Total 149.00" เป็น "Tota114900" (ติดกันหมด)
#:   ของเดิมจับได้ "114" กับ "900" แล้วเอาตัวท้าย → ยอดกลายเป็น 900 บาท
#:   ทั้งที่ลูกค้าจ่ายจริง 149 บาท (ผิดไป 6 เท่า!)
#:   ตอนนี้จะไม่จับเลยเพราะติดกับตัวอักษร → ระบบยอมบอกว่า "อ่านไม่ได้" ซึ่งถูกต้องกว่า
_AMOUNT_PATTERN = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)(?![\d.])")

#: ยอดต้องมากกว่านี้ถึงจะเชื่อ — 0 บาทคือ OCR อ่านพลาดแน่นอน ไม่ใช่ใบเสร็จจริง
_MIN_VALID_AMOUNT = 0.01

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
    # รวมกล่องข้อความที่อยู่แถวเดียวกันกลับเป็นบรรทัด — จำเป็นมาก เพราะ OCR หั่น
    # บรรทัดเดียวเป็นหลายกล่อง ทำให้คำว่า "total" กับตัวเลขยอดหลุดไปคนละกล่อง
    lines = [line.strip() for line in ocr.lines() if line.strip()]

    # ชั้นที่ 1: หาจากคำสำคัญ ("รวมทั้งสิ้น" / "Total")
    keyword_total, keyword_is_exact = _find_total(lines)

    # ชั้นที่ 2-3: ★ ตรวจด้วยคณิตศาสตร์ — ยืนยันของชั้นแรก หรือกู้เคสที่ป้ายอ่านไม่ออก
    candidate = find_total(
        lines, keyword_total=keyword_total, keyword_is_exact=keyword_is_exact
    )
    if candidate is None:
        raise InputValidationError("อ่านยอดเงินจากใบเสร็จไม่ได้ กรุณาถ่ายให้ชัดขึ้น")

    log.info(
        "สรุปยอดเงินได้",
        extra={"amount": candidate.value, "score": candidate.score, "reason": candidate.reason},
    )
    total = candidate.value

    receipt_date = find_date(lines)
    items = find_line_items(lines, total_amount=total)

    # ★ ตรวจค่าที่ดึงมาด้วยกฎทางคณิตศาสตร์ (CONTEXT ข้อ 4)
    #   วันนี้ใช้เป็น "สัญญาณความมั่นใจ" ที่บันทึกไว้เท่านั้น ยังไม่เอาไปกรอง/ปฏิเสธ
    #   เพราะยอดเงินตอนนี้แม่น 96% ผิด 0% อยู่แล้ว เอาไปกรองเสี่ยงลดครอบคลุมโดยไม่จำเป็น
    #   ค่านี้จะถูกใช้จริงตอน template lifecycle (เลื่อนขั้น template ต้องผ่านกฎ)
    rules = validate(total_amount=total, receipt_date=receipt_date, line_items=items)
    log.info(
        "ตรวจกฎค่าที่ดึงมา",
        extra={
            "items": len(items),
            "math_confirmed": rules.math_confirmed,
            "passed": len(rules.passed_checks),
            "failed": list(rules.failed_checks),
        },
    )

    # ★ ชื่อร้านที่ลูกค้าเห็น มาจากทะเบียนร้านเมื่อรู้จัก ไม่ใช่จากที่ OCR อ่านได้
    merchant = resolve(lines)

    return {
        "merchant": merchant.display_name,
        "merchant_code": merchant.code,
        "receipt_no": _find_receipt_no(lines),
        "receipt_date": receipt_date,          # ชื่อตรงกับ Receipt.receipt_date
        "receipt_time": find_time(lines),
        "reference_codes": find_reference_codes(lines),
        "items": items,
        "total_amount": total,
    }


def _find_total(lines: list[str]) -> tuple[float | None, bool]:
    """หายอดรวมสุดท้ายจากบรรทัดที่มีคำสำคัญ · ไม่เจอ → None (ไม่เดาจากเลขที่ใหญ่สุด)

    วิธีเลือกเมื่อมีหลายบรรทัดเข้าข่าย (ใบเสร็จมักมีทั้ง subtotal/VAT/total):
        1. ตัดบรรทัดที่ "ไม่ใช่ยอดสุดท้าย" ทิ้งก่อน (subtotal, ส่วนลด, เงินทอน)
        2. เลือกคำสำคัญที่เจาะจงที่สุด ("รวมทั้งสิ้น" ชนะ "total")
        3. คำสำคัญเท่ากัน → เอาบรรทัดล่างสุด (ยอดสุดท้ายอยู่ท้ายใบเสมอ)
    """
    best: tuple[int, int, float, bool] | None = None  # (คะแนน, ลำดับบรรทัด, ยอด, ตรงเป๊ะ)

    for line_index, line in enumerate(lines):
        if _is_not_final_total(line):
            continue

        matched = _match_total_keyword(line)
        if matched is None:
            continue
        keyword_rank, is_exact = matched

        amount = _last_amount_in(line)
        if amount is None:
            # ★ ป้ายกับตัวเลขอยู่คนละบรรทัด — เจอบ่อยมากบนใบเสร็จจริง
            #   เช่น "Tota!" แล้วบรรทัดถัดไปคือ "1,240"
            #   (เกิดจาก OCR หั่นแถว หรือใบเสร็จพิมพ์ป้ายบน-ตัวเลขล่าง)
            amount = _amount_in_following_lines(lines, line_index)
        if amount is None:
            continue

        candidate = (keyword_rank, line_index, amount, is_exact)
        if best is None or candidate[:2] > best[:2]:
            best = candidate

    return (best[2], best[3]) if best else (None, True)


#: มองต่ำลงไปกี่บรรทัดเพื่อหาตัวเลขของป้ายที่อยู่บรรทัดบน
#: 2 บรรทัดพอ — ไกลกว่านี้เสี่ยงไปหยิบยอดของรายการอื่น
_LOOKAHEAD_LINES = 2


def _amount_in_following_lines(lines: list[str], start: int) -> float | None:
    for line in lines[start + 1: start + 1 + _LOOKAHEAD_LINES]:
        if _is_not_final_total(line):
            break  # เจอ "เงินทอน/ส่วนลด" ก่อน = ป้ายบรรทัดบนไม่ได้คู่กับตัวเลขนี้
        amount = _last_amount_in(line)
        if amount is not None:
            return amount
    return None


def _is_not_final_total(line: str) -> bool:
    lowered = line.lower()
    if any(marker in lowered for marker in _NOT_FINAL_TOTAL):
        return True
    return _looks_like_negative_word(lowered.translate(_OCR_LOOKALIKES))


def _looks_like_negative_word(normalized: str) -> bool:
    """จับคำต้องห้ามที่ OCR อ่านเพี้ยนไปเล็กน้อย (เช่น Subtotal → Suototal)"""
    for token in re.findall(r"[a-z]{5,}", normalized):
        for word in _FUZZY_NEGATIVE_WORDS:
            if SequenceMatcher(None, token, word).ratio() >= _FUZZY_NEGATIVE_THRESHOLD:
                return True
    return False


#: ★ ตัวอักษรที่ OCR สับสนบ่อยบนใบเสร็จกระดาษความร้อน (ตัวเลข ↔ ตัวอักษรที่หน้าตาคล้าย)
#:
#: เจอของจริง: "Total 149.00" ถูกอ่านเป็น "Tota114900" — ตัว l กลายเป็นเลข 1
#: ถ้าไม่แก้ คำว่า total จะหาไม่เจอทั้งที่ OCR อ่านตัวอักษรมาเกือบถูกหมด
#:
#: ⚠ ใช้ "เฉพาะตอนหาคำสำคัญ" เท่านั้น ห้ามใช้กับการอ่านตัวเลขยอดเงินเด็ดขาด
#:   (ถ้าเอาไปแปลงยอดด้วย เลข 1 จะกลายเป็น l แล้วยอดเพี้ยนทั้งใบ)
_OCR_LOOKALIKES = str.maketrans({"1": "l", "0": "o", "5": "s", "8": "b", "|": "l", "!": "l"})

#: ★ คำที่ "ไม่ใช่ยอดสุดท้าย" มักถูก OCR อ่านเพี้ยนจนรายการตายตัวจับไม่ได้
#:   เจอจริง: "Subtotal" → "Suototal" (b เพี้ยนเป็น o)
#:   ถ้าปล่อยผ่าน ระบบจะเอายอดก่อน VAT ไปให้แต้ม → ลูกค้าได้แต้มน้อยกว่าที่ควร
#:   จึงเทียบแบบ "คล้ายพอ" ด้วย เพื่อจับคำที่เพี้ยนไป 1-2 ตัวอักษร
_FUZZY_NEGATIVE_WORDS = ("subtotal", "discount", "change")
_FUZZY_NEGATIVE_THRESHOLD = 0.82


def _match_total_keyword(line: str) -> tuple[int, bool] | None:
    """คืน (คะแนนความเจาะจง, ตรงเป๊ะไหม) ของคำสำคัญที่เจอในบรรทัดนี้

    ★ คำอังกฤษต้องตรงทั้งคำ (word boundary) ไม่ใช่แค่เป็นส่วนหนึ่งของคำอื่น
      — กัน "total" ไปแมตช์กับ "subtotal" ซึ่งเป็นบั๊กที่เคยเกิดจริง
      ส่วนคำไทยใช้การค้นแบบธรรมดา เพราะภาษาไทยไม่มีช่องว่างคั่นคำ

    "ตรงเป๊ะไหม" ใช้ตอนตัดสินใจในที่ที่ต้องการความมั่นใจสูง (ดู total_finder)
    """
    lowered = line.lower()
    # ลองทั้งข้อความตามจริง และข้อความที่แก้ตัวสับสนแล้ว — เผื่อ OCR อ่านคลาดไปนิด
    variants = (lowered, lowered.translate(_OCR_LOOKALIKES))

    for rank, keyword in enumerate(reversed(_TOTAL_KEYWORDS)):
        if keyword.isascii():
            pattern = rf"\b{re.escape(keyword)}"  # ไม่บังคับขอบท้าย — "Tota1149" ติดกับตัวเลข
            if any(re.search(pattern, variant) for variant in variants):
                return rank, True
            if _fuzzy_contains(lowered, keyword):
                return rank, False   # คล้ายพอ แต่ไม่ตรงเป๊ะ
        elif keyword in line:
            return rank, True

    return None


#: คำสำคัญที่ OCR อ่านเพี้ยนไป 1-2 ตัวอักษร ยังต้องจับได้
#: เจอจริงบนใบเสร็จ Sizzler: "Balance Due" ถูกอ่านเป็น "Ralance Due" (B เพี้ยนเป็น R)
#: ผลคือคำสำคัญจับไม่ได้ ระบบเลยไปหยิบ "Total 81" (ซึ่ง 81 คือยอด VAT) มาเป็นยอดรวม
#: ทั้งที่ยอดจริง 1,240 อยู่ในบรรทัดเดียวกับ Balance Due นั่นเอง
#: 0.80 = ยอมให้เพี้ยนได้ 1 ตัวใน 5 ("eotal" ≈ "total")
#: เจอจริงบนใบเสร็จ KFC: "SOFTSERVE Total 35.00" ถูกอ่านเป็น "SOFJSEEotaL 35.00"
#: ปลอดภัยพอเพราะบรรทัดที่มี subtotal/ส่วนลด/เงินทอน ถูกกรองออกไปก่อนหน้านี้แล้ว
_FUZZY_KEYWORD_THRESHOLD = 0.80


def _fuzzy_contains(line: str, keyword: str) -> bool:
    """บรรทัดนี้มีคำที่ "คล้าย keyword พอ" ไหม (เทียบทีละช่วงความยาวเท่ากัน)

    ใช้เฉพาะคำอังกฤษยาว ≥ 5 ตัวอักษร — คำสั้นเทียบแบบคล้ายจะชนกันมั่วเกินไป
    """
    if len(keyword) < 5:
        return False

    window = len(keyword)
    for start in range(len(line) - window + 1):
        chunk = line[start: start + window]
        if SequenceMatcher(None, chunk, keyword).ratio() >= _FUZZY_KEYWORD_THRESHOLD:
            return True
    return False


def _last_amount_in(line: str) -> float | None:
    """จำนวนเงินที่น่าเชื่อถือที่สุดในบรรทัด (ดู amount_parser — กันเวลา/วันที่/รหัส)"""
    return best_amount(line)


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
