"""★ กฎตรวจว่าค่าที่ดึงมาจากใบเสร็จ "สมเหตุสมผลจริง" ก่อนเอาไปให้แต้ม

CONTEXT ข้อ 4 เรียกชั้นนี้ว่า "ตัวทรงพลังสุด" — เพราะถ้า OCR อ่านเลขผิด
กฎทางคณิตศาสตร์จะไม่ลงตัวเอง ระบบรู้ได้เองว่าอ่านพลาดโดยไม่ต้องรอลูกค้าทักท้วง

★ หน้าที่ = "ยืนยันความมั่นใจ" ไม่ใช่ "ปฏิเสธ"
  ผ่านกฎ    → มั่นใจสูงว่าอ่านถูก (เอาไปเลื่อนขั้น template ได้ / ให้แต้มได้เลย)
  ไม่ผ่าน   → ยังไม่ได้แปลว่าอ่านผิด · อาจแค่อ่านรายการไม่ครบ (ชุดเซ็ต/คอลัมน์เหลื่อม)
             การตัดสินว่าจะให้แต้มไหมเป็นของชั้นบน ที่นี่แค่รายงานว่าตรวจอะไรผ่าน/ไม่ผ่าน

★ ทำไมไม่รวมเข้า field_extractor: การ "ดึงค่า" กับการ "ตรวจค่า" คนละหน้าที่
  แยกไว้เพื่อให้ template lifecycle (Step 5 ต่อไป) เอากฎชุดนี้ไปตัดสินการเลื่อนขั้น
  template ได้ โดยไม่ต้องรันการดึงค่าใหม่
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.receipt_data.line_items import LineItem, items_match_total

#: อัตรา VAT ไทย
_VAT_RATE = 0.07

#: ยอมคลาดเคลื่อนตอนตรวจสมการ (ใบเสร็จปัดเศษสตางค์กันคนละแบบ)
_MATH_TOLERANCE = 0.05

#: ยอดที่เป็นไปได้ของใบเสร็จค้าปลีก — นอกช่วงนี้คืออ่านเพี้ยน
_MIN_TOTAL = 1.0
_MAX_TOTAL = 500_000.0

#: ใบเสร็จเก่ากว่านี้ (วัน) = น่าจะอ่านวันที่ผิด หรือลูกค้าเอาใบเก่ามาสแกน
_MAX_AGE_DAYS = 400


@dataclass(frozen=True)
class RuleResult:
    """ผลการตรวจกฎทั้งชุด

    passed_checks / failed_checks เก็บ "ชื่อกฎ" ไว้ทั้งคู่ เพื่อให้ชั้นบน (และหน้า admin)
    เห็นว่าความมั่นใจมาจากกฎไหนบ้าง ไม่ใช่แค่ตัวเลขรวมๆ
    """

    passed_checks: tuple[str, ...] = ()
    failed_checks: tuple[str, ...] = ()
    #: กฎที่ตรวจไม่ได้เพราะข้อมูลไม่พอ (เช่นไม่มีรายการสินค้าให้บวก) — ไม่ใช่ผ่านและไม่ใช่ไม่ผ่าน
    skipped_checks: tuple[str, ...] = ()

    @property
    def has_hard_failure(self) -> bool:
        """มีกฎที่ "ผิดแล้วต้องไม่เชื่อค่านี้" ไหม (ยอดนอกช่วง / วันที่อนาคต)"""
        return any(name in _HARD_RULES for name in self.failed_checks)

    @property
    def math_confirmed(self) -> bool:
        """★ ความสัมพันธ์ทางคณิตศาสตร์ยืนยันแล้วไหม — สัญญาณความมั่นใจที่แข็งที่สุด"""
        return _MATH_RULE in self.passed_checks


#: กฎที่ผิดแล้ว "ห้ามเชื่อค่า" (ต่างจากกฎที่แค่ทำให้มั่นใจน้อยลง)
_HARD_RULES = frozenset({"total_in_range", "date_not_in_future"})

#: ชื่อกฎคณิตศาสตร์ — ยกมาเป็นค่าคงที่เพราะถูกอ้างถึงหลายที่
_MATH_RULE = "line_items_sum_to_total"


def validate(
    *,
    total_amount: float,
    receipt_date: date | None,
    line_items: list[LineItem],
    today: date | None = None,
) -> RuleResult:
    """ตรวจค่าที่ดึงมาทั้งชุด · คืนว่ากฎไหนผ่าน/ไม่ผ่าน/ตรวจไม่ได้

    รับค่าที่ดึงมาแล้ว (ไม่ใช่ OcrResult) เพื่อให้เทสป้อนเคสเจาะจงได้ง่าย
    และเพื่อให้ template lifecycle เรียกซ้ำได้โดยไม่ต้องรัน OCR ใหม่
    """
    today = today or date.today()
    passed: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []

    _check_total_in_range(total_amount, passed, failed)
    _check_line_items_sum(line_items, total_amount, passed, failed, skipped)
    _check_vat_consistency(line_items, total_amount, passed, skipped)
    _check_date(receipt_date, today, passed, failed, skipped)

    return RuleResult(tuple(passed), tuple(failed), tuple(skipped))


def _check_total_in_range(total: float, passed: list[str], failed: list[str]) -> None:
    (passed if _MIN_TOTAL <= total <= _MAX_TOTAL else failed).append("total_in_range")


def _check_line_items_sum(
    line_items: list[LineItem],
    total: float,
    passed: list[str],
    failed: list[str],
    skipped: list[str],
) -> None:
    """★ ผลรวมราคารายการ = ยอดรวมไหม — หลักฐานทางคณิตศาสตร์ว่าอ่านทั้งใบถูก

    ไม่มีรายการที่มีราคา → skip (ชุดเซ็ตที่ของในชุดไม่มีราคา / อ่านรายการไม่ได้)
    ไม่ใช่ "ไม่ผ่าน" เพราะการอ่านรายการไม่ได้ ไม่ได้แปลว่ายอดรวมผิด
    """
    priced = [item for item in line_items if item.price is not None]
    if not priced:
        skipped.append(_MATH_RULE)
    elif items_match_total(line_items, total):
        passed.append(_MATH_RULE)
    else:
        failed.append(_MATH_RULE)


def _check_vat_consistency(
    line_items: list[LineItem],
    total: float,
    passed: list[str],
    skipped: list[str],
) -> None:
    """มีรายการที่หน้าตาเป็น "ยอดย่อย + VAT = ยอดรวม" อยู่ในใบไหม

    ใบเสร็จไทยส่วนใหญ่รวม VAT ในราคาแล้ว (ไม่มีบรรทัด VAT แยก) → กฎนี้จะ skip บ่อย
    ใช้ยืนยันเพิ่มเฉพาะใบที่แยกบรรทัด VAT เท่านั้น
    """
    prices = sorted({item.price for item in line_items if item.price is not None})
    if len(prices) < 2:
        skipped.append("subtotal_plus_vat")
        return

    for subtotal in prices:
        expected_vat = subtotal * _VAT_RATE
        if any(abs(price - expected_vat) <= max(_MATH_TOLERANCE, subtotal * 0.01)
               for price in prices) and abs(subtotal + expected_vat - total) <= _MATH_TOLERANCE:
            passed.append("subtotal_plus_vat")
            return
    skipped.append("subtotal_plus_vat")


def _check_date(
    receipt_date: date | None,
    today: date,
    passed: list[str],
    failed: list[str],
    skipped: list[str],
) -> None:
    """วันที่บนใบเสร็จต้องไม่ใช่อนาคต และไม่เก่าเกินไป

    อ่านวันที่ไม่ได้ → skip (ไม่ใช่ทุกใบมีวันที่ให้อ่าน — ไม่ควรถือเป็นความผิดพลาด)
    """
    if receipt_date is None:
        skipped.append("date_not_in_future")
        skipped.append("date_not_too_old")
        return

    # เผื่อ 1 วันสำหรับ timezone (ใบเสร็จออกปลายวันในโซนที่เร็วกว่าเซิร์ฟเวอร์)
    if (receipt_date - today).days <= 1:
        passed.append("date_not_in_future")
    else:
        failed.append("date_not_in_future")

    if (today - receipt_date).days <= _MAX_AGE_DAYS:
        passed.append("date_not_too_old")
    else:
        failed.append("date_not_too_old")
