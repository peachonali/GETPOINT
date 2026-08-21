"""หา "ยอดรวมสุดท้าย" ของใบเสร็จ — ใจกลางความถูกต้องของทั้งระบบ

อ่านยอดผิด = ลูกค้าได้แต้มผิด = ความเสียหายที่ดึงคืนยากที่สุด
ไฟล์นี้จึงใช้หลักฐานหลายชั้นประกอบกัน ไม่ได้เชื่อคำสำคัญอย่างเดียว

    ชั้นที่ 1  คำสำคัญ      "รวมทั้งสิ้น" / "Total" / "ยอดสุทธิ"
    ชั้นที่ 2  ★ คณิตศาสตร์  ยอดย่อย + VAT = ยอดรวม  ← โกหกยากที่สุด
    ชั้นที่ 3  เงินทอน       เงินสด − เงินทอน = ยอดที่จ่ายจริง

★ ชั้นที่ 2 คือของที่ blueprint เรียกว่า "ตัวทรงพลังสุด" — เพราะถ้า OCR อ่านเลขผิด
  สมการจะไม่ลงตัวเอง ระบบรู้ได้เองว่าอ่านพลาดโดยไม่ต้องรอลูกค้าทักท้วง
  และมันกู้เคสที่ป้ายชื่อเลือนจนอ่านไม่ออกได้ด้วย (เจอจริง: ใบ V-Square
  ที่คำว่า "ยอดสุทธิ" จางหาย แต่ 32.71 + 2.29 = 35.00 ยังบอกเราได้ว่ายอดคือ 35)
"""
from __future__ import annotations

from dataclasses import dataclass

from app.receipt_data.amount_parser import find_amounts

#: ยอมคลาดเคลื่อนได้เท่านี้ตอนตรวจสมการ — ใบเสร็จปัดเศษสตางค์กันคนละแบบ
_MATH_TOLERANCE = 0.05

#: อัตรา VAT ไทย — ใช้ตรวจว่า "ยอดที่เจอ" สมเหตุสมผลกับภาษีที่พิมพ์ไว้ไหม
_VAT_RATE = 0.07


@dataclass(frozen=True)
class TotalCandidate:
    value: float
    #: ยิ่งสูงยิ่งมั่นใจ — ใช้เลือกเมื่อหลายชั้นให้คำตอบต่างกัน
    score: int
    reason: str


def find_total(lines: list[str], *, keyword_total: float | None) -> TotalCandidate | None:
    """สรุปยอดรวมจากหลักฐานทุกชั้น · ไม่มีหลักฐานพอ → None

    keyword_total = ยอดที่ได้จากการหาคำสำคัญ (อาจเป็น None ถ้าป้ายอ่านไม่ออก)
    """
    amounts = _all_amounts(lines)

    # ★ สลิปบัตรเติมเงินมีโครงสร้างของตัวเอง — ตรวจด้วยการลบได้ ตรวจก่อนวิธีอื่น
    if _looks_like_stored_value_slip(lines):
        return _total_from_card_slip(amounts)

    math_total = _total_from_arithmetic(amounts)

    # ★ สองชั้นเห็นตรงกัน = มั่นใจที่สุด (โอกาสที่ OCR จะอ่านผิดแล้วบังเอิญลงตัวพอดีต่ำมาก)
    if keyword_total is not None and math_total is not None:
        if abs(keyword_total - math_total) <= _MATH_TOLERANCE:
            return TotalCandidate(keyword_total, score=100, reason="คำสำคัญ + คณิตศาสตร์ตรงกัน")

        # ขัดแย้งกัน → เชื่อคณิตศาสตร์ เพราะปลอมยากกว่าคำที่อาจอ่านเพี้ยน
        return TotalCandidate(math_total, score=70, reason="คณิตศาสตร์ (ขัดกับคำสำคัญ)")

    if keyword_total is not None:
        return TotalCandidate(keyword_total, score=50, reason="คำสำคัญ")

    if math_total is not None:
        return TotalCandidate(math_total, score=60, reason="คณิตศาสตร์ (ไม่พบคำสำคัญ)")

    return None


#: ร่องรอยที่บอกว่านี่คือ "สลิปบัตรเติมเงิน" ไม่ใช่ใบเสร็จร้านค้าปกติ
#: (เจอในใบเสร็จจริงจาก BigC FoodPark — ใช้บัตรเติมเงินซื้ออาหารในศูนย์อาหาร)
#: เขียนเป็นชิ้นสั้นๆ เพราะ OCR อ่านคำเต็มเพี้ยนบ่อย ("Card Balance" → "Cad Balance")
_CARD_SLIP_MARKERS = ("balance", "baiance", "ยอดคงเหลือ", "คงเหลือ")
_CARD_SLIP_MIN_MARKERS = 2  # ต้องเจอหลายที่ (สลิปมีทั้ง Card Balance และ Net Balance)


def _looks_like_stored_value_slip(lines: list[str]) -> bool:
    text = " ".join(lines).lower()
    return sum(text.count(marker) for marker in _CARD_SLIP_MARKERS) >= _CARD_SLIP_MIN_MARKERS


def _total_from_card_slip(amounts: list[float]) -> TotalCandidate | None:
    """หา "ยอดที่ใช้จ่าย" จากสลิปบัตรเติมเงิน ด้วยความสัมพันธ์ทางคณิตศาสตร์

    โครงสร้างของสลิปแบบนี้เสมอ:
        ยอดในบัตรก่อนใช้ − ยอดที่ใช้ = ยอดคงเหลือ

    ★ ทำไมต้องใช้วิธีนี้แทนการอ่านป้าย "Sale Amount":
      สลิปพวกนี้พิมพ์ป้ายไว้ซ้าย ตัวเลขไว้ขวา พอถ่ายเอียง OCR จะจับคู่เหลื่อมกัน 1 แถว
      แล้วได้ "ยอดในบัตร" มาแทน "ยอดที่ใช้" (เจอจริง: ได้ 225 ทั้งที่จ่ายจริง 75)
      ส่วนการลบนั้นเหลื่อมยังไงก็ยังลงตัวเหมือนเดิม

    ★ ใช้ "ลำดับที่ปรากฏบนสลิป" มาตัดสินความกำกวม:
      ถ้าดูแค่ตัวเลข 300/75/225 จะได้ทั้ง 300−75=225 และ 300−225=75 (ถูกทั้งคู่ทางเลข)
      แต่สลิปพิมพ์เรียงเสมอว่า ยอดในบัตร → ยอดที่ใช้ → ยอดคงเหลือ
      จึงบังคับให้ทั้งสามค่าต้องเรียงตามลำดับนั้นในเอกสารด้วย

    หาไม่เจอ → None (ยอมให้ลูกค้าถ่ายใหม่ ดีกว่าให้แต้มผิด)
    """
    for i, before in enumerate(amounts):
        for j in range(i + 1, len(amounts)):
            spent = amounts[j]
            if spent >= before:
                continue

            remaining = before - spent
            # ยอดคงเหลือต้องอยู่ "หลัง" ยอดที่ใช้ ตามลำดับที่พิมพ์บนสลิป
            if any(abs(amounts[k] - remaining) <= _MATH_TOLERANCE
                   for k in range(j + 1, len(amounts))):
                return TotalCandidate(
                    spent, score=80, reason="สลิปบัตร: ยอดในบัตร − ยอดที่ใช้ = คงเหลือ"
                )

    return None


def _all_amounts(lines: list[str]) -> list[float]:
    """รวมจำนวนเงินทุกตัวที่เจอในใบเสร็จ (ไม่สนว่าอยู่บรรทัดไหน)"""
    values: list[float] = []
    for line in lines:
        values.extend(amount.value for amount in find_amounts(line) if amount.has_decimals)
    return values


def _total_from_arithmetic(amounts: list[float]) -> float | None:
    """หาตัวเลข c ที่มี a + b = c อยู่ในใบเสร็จ (ยอดย่อย + VAT = ยอดรวม)

    เงื่อนไขเพิ่มเพื่อกันบังเอิญ:
      - b (ที่ควรเป็น VAT) ต้องประมาณ 7% ของ a จริงๆ
      - c ต้องเป็นตัวที่ใหญ่ที่สุดในบรรดาสามตัว
    ถ้าเจอหลายชุดที่เข้าเงื่อนไข ให้เลือก c ที่มากที่สุด (ยอดสุดท้ายย่อมใหญ่สุด)
    """
    unique = sorted(set(amounts))
    if len(unique) < 3:
        return None

    best: float | None = None

    for subtotal in unique:
        for vat in unique:
            if vat >= subtotal:
                continue  # VAT ต้องน้อยกว่ายอดย่อยเสมอ
            # ตรวจว่า vat เป็นภาษี 7% ของ subtotal จริงไหม (ยอมคลาดเคลื่อนเล็กน้อย)
            if abs(vat - subtotal * _VAT_RATE) > max(_MATH_TOLERANCE, subtotal * 0.005):
                continue

            target = subtotal + vat
            for candidate in unique:
                if abs(candidate - target) <= _MATH_TOLERANCE and (best is None or candidate > best):
                    best = candidate

    return best
