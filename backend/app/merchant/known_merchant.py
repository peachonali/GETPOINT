"""ทะเบียนร้านที่ระบบรู้จัก + วิธีจับว่าใบเสร็จใบนี้มาจากร้านไหน

★ ทำไมต้องมี "รหัสร้าน" ทั้งที่อ่านชื่อร้านได้อยู่แล้ว:
    ชื่อร้านที่ OCR อ่านได้ ใช้ตัดสินใจอะไรไม่ได้เลย — วัดจริงกับใบเดียวกันสองมุม
        รูปหนึ่ง "CRG-KFC 12IO2 (KEC-BIO C NAKORNSAVAN)"
        อีกรูป  "2330 Host: Prapapan #2330 BOX AI1 Easy"
    แต่ระบบต้องรู้ว่า "ร้านไหน" เพื่อ:
        1. เลือก template ของร้านนั้นมาดึงค่า (หัวใจของ Step 5)
        2. เลือกสูตรคิดแต้ม/กลยุทธ์ A-B ต่อร้าน
        3. แสดงชื่อร้านที่ถูกต้องให้ลูกค้าดู แทนข้อความมั่วๆ จาก OCR

★ สัญญาณหลัก = เลขผู้เสียภาษี 13 หลัก (ไม่ใช่ชื่อร้าน)
    - พิมพ์อยู่บนใบเสร็จทุกใบตามกฎหมาย
    - เป็นตัวเลขล้วน OCR อ่านเพี้ยนน้อยกว่าตัวอักษรมาก
    - ไม่ซ้ำข้ามบริษัท และไม่เปลี่ยนตามสาขา/แคชเชียร์/รูปแบบใบเสร็จ
    วัดกับใบจริง 28 รูป: อ่านเลขนี้ได้ตรง 19 ใบ ส่วนที่เหลือใช้คำเฉพาะช่วย

⚠ ไฟล์นี้เป็น "ทะเบียนที่คนดูแล" ไม่ใช่ template
   template (รู้ว่าค่าอยู่พิกัดไหนบนใบ) เป็นคนละเรื่องและอยู่ในไฟล์อื่น
   วันที่ร้านมีเยอะจนแก้ไฟล์ไม่ไหว ค่อยย้ายไปตาราง merchants — ยังไม่ใช่วันนี้
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher


@dataclass(frozen=True)
class KnownMerchant:
    """ร้าน 1 ร้านที่ระบบรู้จัก"""

    #: รหัสภายในระบบ — คงที่ตลอดไป ใช้ผูกกับ template/สูตรแต้ม (ห้ามเปลี่ยน)
    code: str
    #: ชื่อที่แสดงให้ลูกค้าเห็น (แทนข้อความที่ OCR อ่านมั่วๆ)
    display_name: str
    #: เลขผู้เสียภาษี 13 หลักของนิติบุคคลเจ้าของร้าน — สัญญาณหลัก
    tax_ids: tuple[str, ...] = ()
    #: คำเฉพาะที่โผล่บนใบเสร็จร้านนี้เท่านั้น — ใช้เมื่ออ่านเลขภาษีไม่ได้
    #:
    #: ★ ต้องเลือกคำที่ "ไม่โผล่บนใบของร้านอื่น" ให้ได้จริง
    #:   เจอจริง: ใบ KFC และ DQ ในชุดทดสอบพิมพ์ที่ตั้งสาขาว่า "BIG C NAKORNSAWAN"
    #:   ถ้าใช้คำว่า "big c" เป็นคำเฉพาะของ BigC ใบ KFC ทุกใบจะถูกจับเป็นร้าน BigC
    keywords: tuple[str, ...] = field(default_factory=tuple)


#: ★ เรียงจาก "เฉพาะเจาะจงที่สุด" ลงไป — ตัวแรกที่ตรงเป็นผู้ชนะ
#:
#: เลขภาษีมาจากใบเสร็จจริงในชุดทดสอบ (tests/fixtures/receipts/)
#: เพิ่มร้านใหม่: เอาใบเสร็จจริงมาดูเลขภาษี แล้วเติมแถวใหม่ที่นี่
KNOWN_MERCHANTS: tuple[KnownMerchant, ...] = (
    KnownMerchant(
        code="kfc",
        display_name="KFC",
        tax_ids=("0105532021090",),
        keywords=("kfc",),
    ),
    KnownMerchant(
        code="dq",
        display_name="Dairy Queen",
        tax_ids=("0105525046201",),
        # "talktodq" มาจาก URL แบบสอบถามท้ายใบ — อ่านได้ชัดกว่าโลโก้
        keywords=("talktodq", "minor dq", "dq cashier"),
    ),
    KnownMerchant(
        code="sizzler",
        display_name="Sizzler",
        tax_ids=("0105551088013",),
        keywords=("sizzler",),
    ),
    KnownMerchant(
        code="the-pizza-company",
        display_name="The Pizza Company",
        tax_ids=("0735560089449",),
        keywords=("pizza",),
    ),
    KnownMerchant(
        code="vsquare",
        display_name="V-Square Department Store",
        tax_ids=("0605545000024",),
        keywords=("v-square", "vsquare", "vsquareplaza"),
    ),
    KnownMerchant(
        code="bigc-foodpark",
        display_name="BIG C FOODPark",
        tax_ids=("0107536000633",),
        # ห้ามใช้ "big c" — ใบ KFC/DQ ในห้างเดียวกันก็มีคำนี้ (ดูหมายเหตุที่ field keywords)
        keywords=("foodpark", "supercenter"),
    ),
)

#: เลขผู้เสียภาษีนิติบุคคลไทยมี 13 หลักเสมอ
_TAX_ID_PATTERN = re.compile(r"\d{13}")

#: ตัวเลขที่ OCR มักอ่านสลับกับตัวอักษรบนกระดาษความร้อน — ใช้ตอนหา "คำเฉพาะ" เท่านั้น
#: เจอจริง (#19): "FOODPark" ถูกอ่านเป็น "F0ODPark" (ตัว O เป็นเลขศูนย์)
#: ⚠ ห้ามใช้กับเลขภาษีเด็ดขาด — เลข 0 จะกลายเป็นตัว o แล้วเทียบไม่ตรงทั้งใบ
_KEYWORD_LOOKALIKES = str.maketrans({"0": "o", "1": "i", "5": "s", "8": "b"})


def identify(lines: list[str]) -> KnownMerchant | None:
    """ใบเสร็จนี้มาจากร้านไหน · ไม่รู้จัก → None (ไม่เดา)

    ลำดับความน่าเชื่อถือ:
        1. เลขผู้เสียภาษีตรงกับที่ขึ้นทะเบียนไว้ — แน่นอนที่สุด
        2. คำเฉพาะของร้าน — ใช้เมื่ออ่านเลขภาษีไม่ได้

    คืน None เป็นเรื่องปกติ ไม่ใช่ข้อผิดพลาด — ร้านที่ยังไม่ขึ้นทะเบียนจะไปเข้าทาง
    "ร้านใหม่" ของ merchant_resolver
    """
    return _by_tax_id(lines) or _by_keyword(lines)


def _by_tax_id(lines: list[str]) -> KnownMerchant | None:
    """หาเลข 13 หลักบนใบเสร็จ แล้วเทียบกับทะเบียน

    ลบช่องว่างออกก่อน เพราะ OCR แทรกช่องว่างกลางเลขได้ (เจอจริงบนใบ DQ:
    "TAX ID: 0105525 046201")
    """
    digits_in_receipt = {
        found
        for line in lines
        for found in _TAX_ID_PATTERN.findall(re.sub(r"[\s\-]", "", line))
    }
    if not digits_in_receipt:
        return None

    for merchant in KNOWN_MERCHANTS:
        if digits_in_receipt & set(merchant.tax_ids):
            return merchant
    return None


def _by_keyword(lines: list[str]) -> KnownMerchant | None:
    text = " ".join(lines).lower()
    normalized = text.translate(_KEYWORD_LOOKALIKES)

    for merchant in KNOWN_MERCHANTS:
        for word in merchant.keywords:
            if word in text or word in normalized:
                return merchant
            if _fuzzy_contains(normalized, word):
                return merchant
    return None


#: คำเฉพาะที่ OCR อ่านเพี้ยนไป 1 ตัวอักษร ยังต้องจับได้
#: เจอจริง (#18): "THE PIZZA COMPANY" ถูกอ่านเป็น "emTHE / PIZA / COMPAAY" (z หายไปตัว)
#:
#: ★ เลข 0.80 มาจากการวัดกับใบจริง 28 รูป ไม่ได้ตั้งลอยๆ:
#:     0.85 → ถูก 27/28 · ผิด 0     (ใบ Pizza #18 ยังจับไม่ได้)
#:     0.80 → ถูก 28/28 · ผิด 0     ← เลือกอันนี้
#:   ต่ำกว่านี้ไม่ได้อะไรเพิ่ม แต่เพิ่มโอกาสจับผิดร้านซึ่งเป็นความเสียหายที่แพงกว่ามาก
_KEYWORD_FUZZY_THRESHOLD = 0.80


def _fuzzy_contains(text: str, keyword: str) -> bool:
    """ข้อความนี้มีคำที่ "คล้าย keyword พอ" ไหม (เลื่อนหน้าต่างเทียบทีละช่วง)

    ★ คำสั้นปลอดภัยอยู่แล้วโดยไม่ต้องมีเงื่อนไขความยาวเพิ่ม:
      หน้าต่างที่เทียบยาวเท่ากับ keyword เสมอ ดังนั้นคำ 3 ตัวอักษรที่ต่างกัน 1 ตัว
      จะได้คะแนนแค่ 0.67 ซึ่งต่ำกว่าเกณฑ์ 0.85 → เท่ากับบังคับให้ตรงเป๊ะไปในตัว
      (เคยเขียนเงื่อนไขความยาวไว้ แล้วพบตอนทดลองทำลายโค้ดว่ามันไม่มีผลอะไรเลย
       — เงื่อนไขที่ไม่มีผลคือโค้ดที่หลอกคนอ่านว่ามีการป้องกัน จึงถอดออก)
    """
    window = len(keyword)
    for start in range(len(text) - window + 1):
        chunk = text[start: start + window]
        if SequenceMatcher(None, chunk, keyword).ratio() >= _KEYWORD_FUZZY_THRESHOLD:
            return True
    return False
