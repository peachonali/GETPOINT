"""อ่าน "ชื่อร้าน/สาขา" จากใบเสร็จ

★ ทำไมของเดิม (เอาบรรทัดแรก) ใช้ไม่ได้:
    บรรทัดแรกของใบเสร็จจริงมักไม่ใช่ชื่อร้าน แต่เป็น
        "TAX INVOICE (ABB) : 23191"          (Dairy Queen)
        "www.talktoDQthailand.com"           (Dairy Queen อีกใบ)
        "We appuclud: yeu con-nent..."       (Sizzler — ข้อความเชิญชวนรีวิว)
        "Bangkok Bank ธนาคารกรุงเทพ"          (สลิปบัตร — นี่คือธนาคาร ไม่ใช่ร้าน)

★ วิธีที่ใช้: ให้คะแนนแต่ละบรรทัดในส่วนหัวใบเสร็จ แล้วเลือกตัวที่ "เหมือนชื่อร้านที่สุด"
    บวกคะแนน — อยู่บนสุด, มีตัวอักษรเยอะ, ความยาวพอเหมาะ
    ลบคะแนน — เป็น URL, เป็นหัวข้อเอกสาร (ใบกำกับภาษี), เป็นเลขล้วน, เป็นชื่อธนาคาร

★ รวมบรรทัด "สาขา" เข้าไปด้วยถ้าอยู่ติดกัน — ร้านเดียวกันคนละสาขาต้องแยกออกจากกัน
  (เช่น "KFC-12102" + "BIG C NAKORNSAWAN")
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

#: ดูแค่ส่วนหัว — ชื่อร้านอยู่บนสุดเสมอ ลึกกว่านี้จะเจอรายการสินค้า
_HEADER_LINES = 8

#: หัวข้อเอกสาร/ข้อความมาตรฐาน — ไม่ใช่ชื่อร้าน
_BOILERPLATE = (
    "tax invoice", "tax id", "reg id", "receipt", "abb", "vat included", "vat",
    "thank you", "customer copy", "merchant copy", "sale (pos)", "qr promptpay",
    "ใบกำกับภาษี", "ใบเสร็จ", "อย่างย่อ", "ขอบคุณ", "ราคารวมภาษี", "เลขประจำตัว",
    "www.", "http", ".com", ".co.th",
)

#: ธนาคาร/ผู้ให้บริการชำระเงิน — บนสลิปบัตรพวกนี้อยู่บนสุด แต่ "ร้านค้า" คือบรรทัดถัดไป
_PAYMENT_PROVIDERS = (
    "bangkok bank", "ธนาคารกรุงเทพ", "kasikorn", "กสิกร", "scb", "ไทยพาณิชย์",
    "krungthai", "กรุงไทย", "krungsri", "กรุงศรี", "ttb", "promptpay", "visa", "mastercard",
)

#: ชื่อร้านที่สั้นหรือยาวเกินนี้ไม่น่าใช่ชื่อร้าน
_MIN_LENGTH = 3
_MAX_LENGTH = 60

#: ต้องมีตัวอักษร (ไม่ใช่เลข/สัญลักษณ์) อย่างน้อยเท่านี้ของความยาว
#: 0.3 เพื่อให้รหัสสาขาอย่าง "KFC-12102" ผ่านได้ (ตัวอักษร 3 จาก 9)
#: แต่ยังกันเลขล้วนอย่าง "12102-002-0044557" ออกไป (ตัวอักษร 0)
_MIN_LETTER_RATIO = 0.3

#: บรรทัดที่เป็นเครื่องหมายคั่น เช่น "*****FOODPark*****"
_DECORATION = re.compile(r"^[\W_]+|[\W_]+$")

#: ★ บรรทัดที่พูดถึง "เงิน" ไม่ใช่ชื่อร้าน — ชื่อร้านไม่มีราคาต่อท้าย
#:   จำเป็นเพราะส่วนหัวใบเสร็จบางใบสั้นมาก จนบรรทัดยอดเงินขึ้นมาอยู่ใน 8 บรรทัดแรก
_MONEY_WORDS = (
    "total", "amt", "cash", "change", "balance", "subtotal",
    "รวม", "ยอด", "เงินสด", "เงินทอน", "บาท", "ราคา", "ส่วนลด",
)

#: ราคา (มีสตางค์) — บรรทัดที่มีตัวเลขแบบนี้คือรายการสินค้า/ยอด ไม่ใช่ชื่อร้าน
_PRICE_LIKE = re.compile(r"\d+[.,]\d{2}\b")


def find_merchant(lines: list[str]) -> str | None:
    """ชื่อร้าน (+ สาขาถ้ามี) · หาไม่ได้ → None

    คืน None ดีกว่าคืนขยะ — ชื่อร้านผิดทำให้ template ผิดใบและกันซ้ำเพี้ยน
    """
    candidates = _score_header_lines(lines[:_HEADER_LINES])
    if not candidates:
        return None

    best_index, _, best_text = max(candidates, key=lambda item: (item[1], -item[0]))

    branch = _branch_after(candidates, best_index)
    return f"{best_text} {branch}".strip() if branch else best_text


def _score_header_lines(header: list[str]) -> list[tuple[int, int, str]]:
    """คืน (ลำดับบรรทัด, คะแนน, ข้อความที่ล้างแล้ว) ของบรรทัดที่พอเป็นชื่อร้านได้"""
    scored: list[tuple[int, int, str]] = []

    for index, raw in enumerate(header):
        text = _DECORATION.sub("", raw).strip()
        if not _could_be_name(text):
            continue

        score = 10 - index * 2                       # ยิ่งอยู่บนยิ่งน่าจะใช่
        if _is_payment_provider(text):
            score -= 12                              # ธนาคารบนสลิป — ไม่ใช่ร้าน
        if any(char.isdigit() for char in text):
            score -= 1                               # มีตัวเลขปนได้ (รหัสสาขา) แต่ลดความมั่นใจ
        if text.isupper():
            score += 2                               # ชื่อร้านมักพิมพ์ตัวใหญ่ทั้งหมด
        scored.append((index, score, text))

    return scored


def _could_be_name(text: str) -> bool:
    if not (_MIN_LENGTH <= len(text) <= _MAX_LENGTH):
        return False

    lowered = text.lower()
    if any(marker in lowered for marker in _BOILERPLATE):
        return False
    if any(word in lowered for word in _MONEY_WORDS):
        return False
    if _PRICE_LIKE.search(text):
        return False

    letters = sum(char.isalpha() for char in text)
    return letters / len(text) >= _MIN_LETTER_RATIO


#: ชื่อธนาคารที่ OCR อ่านเพี้ยน ยังต้องจับได้
#: เจอจริง: "ธนาคารกรุงเทพ" ถูกอ่านเป็น "ธนาตารกรุวเทน" (ต→ค, ว→ง, น→พ)
#: ถ้าจับไม่ได้ ระบบจะเอาชื่อธนาคารไปเป็นชื่อร้าน ทั้งที่ร้านจริงคือ KFC
_PROVIDER_SIMILARITY = 0.70

#: ธนาคารไทยขึ้นต้นด้วยคำนี้เสมอ — ตัวช่วยที่ทนต่อ OCR เพี้ยนได้ดีที่สุด
_THAI_BANK_PREFIX = "ธนา"


def _is_payment_provider(text: str) -> bool:
    lowered = text.lower()
    if any(provider in lowered for provider in _PAYMENT_PROVIDERS):
        return True
    if _THAI_BANK_PREFIX in text:
        return True

    # เทียบแบบ "คล้ายพอ" เผื่อ OCR อ่านชื่อธนาคารเพี้ยน
    return any(
        SequenceMatcher(None, lowered, provider).ratio() >= _PROVIDER_SIMILARITY
        for provider in _PAYMENT_PROVIDERS
    )


def _branch_after(candidates: list[tuple[int, int, str]], best_index: int) -> str | None:
    """บรรทัดถัดจากชื่อร้านมักเป็นสาขา — เอามาต่อท้ายเพื่อแยกสาขาออกจากกัน

    เช่น "KFC-12102" (ร้าน) + "BIG C NAKORNSAWAN" (สาขา)
    """
    for index, _score, text in candidates:
        if index == best_index + 1 and not _is_payment_provider(text):
            return text
    return None
