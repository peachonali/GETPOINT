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
