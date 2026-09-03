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

import re
from dataclasses import dataclass

from app.receipt_data.amount_parser import best_amount, find_amounts

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


def find_total(
    lines: list[str],
    *,
    keyword_total: float | None,
    keyword_is_exact: bool = True,
) -> TotalCandidate | None:
    """สรุปยอดรวมจากหลักฐานทุกชั้น · ไม่มีหลักฐานพอ → None

    keyword_total    ยอดที่ได้จากการหาคำสำคัญ (None ถ้าป้ายอ่านไม่ออก)
    keyword_is_exact คำสำคัญตรงเป๊ะไหม หรือแค่ "คล้ายพอ" (fuzzy)
                     ใช้ตัดสินในที่ที่ต้องการความมั่นใจสูงเป็นพิเศษ
    """
    amounts = _all_amounts(lines)

    # ★ สลิปบัตรเติมเงินมีโครงสร้างของตัวเอง — ใช้กฎเฉพาะของมัน
    if _looks_like_stored_value_slip(lines):
        # 1) ★ ความสัมพันธ์ ยอดในบัตร − ยอดที่ใช้ = คงเหลือ — เชื่อถือได้ที่สุด
        #    เพราะต้องมีตัวเลขสามตัวลงตัวพร้อมกัน โอกาสที่ OCR อ่านผิดแล้วยังลงตัวต่ำมาก
        from_subtraction = _total_from_card_slip(amounts)
        if from_subtraction is not None:
            return from_subtraction

        # 2) ลบไม่ลงตัว (OCR อ่านตกไปตัวหนึ่ง) → ใช้บรรทัดท้าย "Card No:xxxx AMT: yyy"
        #    ดีตรงที่ป้ายกับตัวเลขอยู่แถวเดียวกัน จึงไม่มีปัญหาคอลัมน์เหลื่อม
        #    แต่เชื่อได้น้อยกว่าข้อ 1 เพราะบางใบมีตัวเลขคอลัมน์ข้างๆ ปนเข้ามา
        from_footer = _total_from_card_footer(lines)
        if from_footer is not None:
            return from_footer

        # ลบไม่ลงตัว (OCR อ่านเลขตกไปตัวหนึ่ง) → ยอมใช้ป้าย แต่ต้องตรงเป๊ะเท่านั้น
        # เพราะบนสลิปพวกนี้ป้ายที่อ่านเพี้ยนมักมาคู่กับตัวเลขที่อ่านเพี้ยนด้วย
        # (เจอจริง: "Sale Arneunt AMT 76.00" ทั้งที่ยอดจริง 75.00)
        if keyword_total is not None and keyword_is_exact:
            return TotalCandidate(keyword_total, score=45, reason="สลิปบัตร: ป้ายตรงเป๊ะ")
        return None

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

    # ★ ทางสุดท้าย: ยอดที่ "ติดป้ายสกุลเงิน" มาเอง (THB / ฿ / บาท)
    #   บนสลิปชำระเงิน ตัวเลขที่มีสกุลเงินกำกับคือยอดธุรกรรมเสมอ ส่วนเลขอื่นเป็นรหัส
    #   เจอจริงบนสลิป QR PromptPay ของ KFC: คำว่า "Total" หลุดไปอยู่คนละบรรทัด
    #   กับยอด แต่ "THB528.00" บอกตัวเองอยู่แล้วว่าเป็นเงิน
    currency_total = _only_currency_marked_amount(lines)
    if currency_total is not None:
        return TotalCandidate(currency_total, score=40, reason="ยอดที่มีสกุลเงินกำกับ")

    # ★ ทางสุดท้ายจริงๆ: มี "ยอดย่อย" แต่หา "ยอดรวม" ไม่เจอเลย
    #   ใบเสร็จไทยส่วนใหญ่รวม VAT ในราคาแล้ว (พิมพ์ว่า "ราคารวมภาษีมูลค่าเพิ่มแล้ว")
    #   ยอดย่อยจึงเท่ากับยอดที่จ่ายจริง
    #   เจอจริง: Dairy Queen ("Order Total" ถูกอ่านเหลือ "order") และ Pizza Company
    #   ("Total 2,69" อ่านตกหลักจนใช้ไม่ได้) — ทั้งคู่มี Subtotal ที่ถูกต้องอยู่
    #
    #   ⚠ ใช้เมื่อ "ไม่มี VAT แยกบรรทัด" เท่านั้น — ถ้ามี VAT แยก แปลว่าต้องบวกเพิ่ม
    #     และกรณีนั้นชั้นคณิตศาสตร์ด้านบนจะจับได้เองอยู่แล้ว
    subtotal = _subtotal_amount(lines)
    if subtotal is not None and not _has_separate_vat(lines):
        return TotalCandidate(subtotal, score=30, reason="ยอดย่อย (ไม่พบยอดรวม, VAT รวมในราคา)")

    return None


#: คำที่บอกว่าบรรทัดนี้คือ "ยอดย่อย"
_SUBTOTAL_MARKERS = ("subtotal", "sub total", "ยอดรวมย่อย", "รวมย่อย")

#: คำที่บอกว่าใบเสร็จ "แยกบรรทัด VAT" ไว้ต่างหาก (ต้องบวกเพิ่ม ไม่ใช่รวมแล้ว)
_VAT_MARKERS = ("vat", "uat", "ภาษีมูลค่าเพิ่ม", "ภ.พ.", "ภพ.")


def _subtotal_amount(lines: list[str]) -> float | None:
    """ยอดย่อยที่มากที่สุดในใบเสร็จ (ใบเดียวอาจมีหลายบรรทัดย่อย)"""
    values = [
        amount for line in lines
        if any(marker in line.lower() for marker in _SUBTOTAL_MARKERS)
        for amount in [best_amount(line)] if amount is not None
    ]
    return max(values) if values else None


def _has_separate_vat(lines: list[str]) -> bool:
    """ใบเสร็จนี้แยกบรรทัด VAT พร้อมจำนวนเงินไว้ไหม"""
    for line in lines:
        lowered = line.lower()
        if any(marker in lowered for marker in _VAT_MARKERS) and best_amount(line) is not None:
            return True
    return False


def _only_currency_marked_amount(lines: list[str]) -> float | None:
    """ยอดที่มีสกุลเงินกำกับ · ใช้ได้เมื่อ "มีค่าเดียว" เท่านั้น

    ถ้ามีหลายค่าแปลว่ากำกวม (ไม่รู้ว่าอันไหนยอดจ่ายจริง) → ไม่เดา
    """
    marked: set[float] = set()
    for line in lines:
        if _is_payment_context(line):
            continue
        marked.update(a.value for a in find_amounts(line) if a.has_currency and a.has_decimals)

    return marked.pop() if len(marked) == 1 else None


#: บรรทัดเงินสด/เงินทอน — มีสกุลเงินกำกับเหมือนกันแต่ไม่ใช่ยอดที่ต้องคิดแต้ม
_PAYMENT_CONTEXT = ("cash", "change", "เงินสด", "เงินทอน", "ทอน", "balance")


def _is_payment_context(line: str) -> bool:
    lowered = line.lower()
    return any(word in lowered for word in _PAYMENT_CONTEXT)


#: ร่องรอยที่บอกว่านี่คือ "สลิปบัตรเติมเงิน" ไม่ใช่ใบเสร็จร้านค้าปกติ
#: (เจอในใบเสร็จจริงจาก BigC FoodPark — ใช้บัตรเติมเงินซื้ออาหารในศูนย์อาหาร)
#: เขียนเป็นชิ้นสั้นๆ เพราะ OCR อ่านคำเต็มเพี้ยนบ่อย ("Card Balance" → "Cad Balance")
_CARD_SLIP_MARKERS = ("balance", "baiance", "ยอดคงเหลือ", "คงเหลือ")
_CARD_SLIP_MIN_MARKERS = 2  # ต้องเจอหลายที่ (สลิปมีทั้ง Card Balance และ Net Balance)


def _looks_like_stored_value_slip(lines: list[str]) -> bool:
    text = " ".join(lines).lower()
    return sum(text.count(marker) for marker in _CARD_SLIP_MARKERS) >= _CARD_SLIP_MIN_MARKERS


#: บรรทัดท้ายสลิปที่ระบุยอดธุรกรรม — "Card No:3210019969783 AMT: 10.00"
#: (เลขบัตรถูกกรองทิ้งโดย amount_parser อยู่แล้วเพราะยาวเกินกว่าจะเป็นเงิน)
_CARD_FOOTER = re.compile(r"c\w?rd\s*n[o0]", re.IGNORECASE)


def _total_from_card_footer(lines: list[str]) -> TotalCandidate | None:
    """ยอดจากบรรทัด "Card No ... AMT: xxx" ท้ายสลิป

    ★ ทำไมเชื่อบรรทัดนี้มากกว่าป้าย "Sale Amount":
      ป้ายกับตัวเลขบนสลิปอยู่คนละคอลัมน์ (ซ้าย/ขวา) พอถ่ายเอียง OCR จะจับคู่เหลื่อมแถว
      แล้วได้ "ยอดคงเหลือในบัตร" มาแทน "ยอดที่ใช้จ่าย" — เจอจริงทั้งใบ #11 และ #14
      ส่วนบรรทัดท้ายนี้มีทั้งป้ายและตัวเลขอยู่ในแถวเดียวกัน จึงไม่มีปัญหาเหลื่อม
    """
    for line in lines:
        if _CARD_FOOTER.search(line):
            amount = best_amount(line)
            if amount is not None:
                return TotalCandidate(amount, score=85, reason="สลิปบัตร: บรรทัดท้าย Card No")
    return None


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
