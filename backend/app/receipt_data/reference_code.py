"""ดึง "เลขอ้างอิงของธุรกรรม" จากใบเสร็จ — สัญญาณที่แข็งที่สุดในการบอกว่าใบไหนคือใบไหน

★ ทำไมต้องมีไฟล์นี้ (ปัญหาที่พิสูจน์แล้วด้วยของจริง):
    ลายนิ้วมือเดิมใช้ ชื่อร้าน + เลขที่ + วันที่ + ยอด
    แต่ "ชื่อร้าน" อ่านได้ไม่คงที่ระหว่างรูปของใบเดียวกัน
        ใบ KFC 149 ใบเดียวกัน  รูปหนึ่งอ่านชื่อร้านได้ "CRG-KFC 12IO2 (KEC-BIO C ...)"
                                อีกรูปอ่านได้ "2330 Host: Prapapan #2330 BOX AI1 Easy"
    → ลายนิ้วมือคนละค่า → ลูกค้าถ่ายใบเดิมส่งซ้ำได้แต้มสองเท่า

    ขณะที่ "เลขอ้างอิง" อ่านได้ตรงกันทั้งสองรูป (วัดจากใบจริง 28 รูป):
        Invoice ID: 12102-002-0044557   ← เหมือนกันเป๊ะทั้งสองรูป
        TRANS ID.  003646657141          ← เหมือนกันเป๊ะทั้งสองรูป

★ หลักที่ยึด: ต้อง "มีป้ายกำกับ" เท่านั้นถึงจะเก็บ
    ห้ามเก็บตัวเลขยาวๆ ทุกตัวบนใบเสร็จ เพราะจะไปโดนเลขที่ "ไม่ใช่ของธุรกรรมนี้":
        TAX ID: 0105532021090      ← เลขผู้เสียภาษีของร้าน — ทุกใบของร้านนี้เหมือนกัน
        POS ID: E076000003A0009    ← เลขเครื่องแคชเชียร์ — ทุกใบที่ออกจากเครื่องนี้เหมือนกัน
        MER#000002206415630        ← รหัสร้านค้าฝั่งธนาคาร — ทุกสลิปของร้านนี้เหมือนกัน
    ถ้าเก็บพวกนี้เข้ามา ระบบจะมองว่า "ลูกค้าซื้อ KFC 149 บาทเมื่อวานกับวันนี้"
    เป็นใบเดียวกัน แล้วปฏิเสธแต้มของวันนี้ — ลูกค้าเสียแต้มที่ควรได้

⚠ เป้าหมายของไฟล์นี้คือ "อ่านได้ตรงกันทุกครั้ง" ไม่ใช่ "อ่านได้ถูกต้อง"
   ถ้า OCR อ่าน 727030981 เพี้ยนเป็น 72A030981 ทั้งสองรูปเหมือนกัน ก็ใช้กันซ้ำได้ดีเท่ากัน
   (วัดจากใบจริง: BigC #14/#17 อ่านเพี้ยนแบบเดียวกันทั้งคู่)
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

#: ป้ายที่บอกว่า "ตัวเลขถัดจากนี้คือเลขของธุรกรรมนี้"
#:
#: เก็บเฉพาะป้ายที่ผูกกับ "การซื้อครั้งนี้" เท่านั้น — ป้ายที่ผูกกับร้าน/เครื่อง/บัตร
#: (tax id, pos id, mer, tid, reg id, restaurant id, card no, vid, batch) ไม่อยู่ในรายการ
#: โดยตั้งใจ เพราะค่าของมันเหมือนกันข้ามใบ (ดูหัวไฟล์)
_TRANSACTION_LABELS = (
    "invoice",   # KFC: "Invoice ID: 12102-002-0044557" · DQ: "TAX INVOICE (ABB): 23191"
    "inv",       # BigC: "Tax INV 713201824"
    "trans",     # สลิปธนาคาร: "TRANS ID. 003646657141"
    "trace",     # สลิปธนาคาร: "TRACE#071055" — เลขวิ่งต่อธุรกรรมของเครื่องรูดบัตร
    "stan",      # สลิปธนาคาร: "STAN#071650"
    "appr",      # สลิปธนาคาร: "APPR.CODE#922535" — รหัสอนุมัติจากธนาคาร
    "ref",       # สลิปธนาคาร: "REF#2 4785317422568..."
    "เลขที่",     # ใบเสร็จไทยทั่วไป
)

#: ตัวอักษรที่ OCR สับสนบ่อยบนกระดาษความร้อน — ใช้ตอน "หาป้าย" เท่านั้น
#:
#: เจอจริงทั้งหมดนี้บนใบเสร็จชุดทดสอบ:
#:     "Invoice"  → "Inuoice" / "InUoice" / "Invgice"   (v ↔ u)
#:     "VAT"      → "UAT"                                (v ↔ u)
#:     "Tax"      → "1ax" / "Iax"                        (t ↔ 1/I)
#: ⚠ ห้ามเอาไปใช้กับ "ค่า" ของเลขอ้างอิงเด็ดขาด — เลข 0 จะกลายเป็นตัว o แล้วเทียบไม่ตรง
_LABEL_LOOKALIKES = str.maketrans({"0": "o", "1": "i", "5": "s", "8": "b", "|": "i", "!": "i", "u": "v"})

#: ป้ายที่ OCR อ่านเพี้ยน 1-2 ตัวอักษร ยังต้องจับได้ (เจอจริง: "Inuoce1" ของใบ KFC #3)
#: 0.80 = ยอมให้เพี้ยนได้ราว 1 ตัวใน 5
_LABEL_FUZZY_THRESHOLD = 0.80

#: ค่าที่จะนับเป็นเลขอ้างอิงต้องมีตัวเลขอย่างน้อยเท่านี้
#: 5 หลัก: กันเลขจำนวนเงิน/จำนวนชิ้น/เลขคิวสั้นๆ หลุดเข้ามา
_MIN_DIGITS = 5

#: มองข้ามโทเคนที่ "ไม่มีตัวเลข" ได้กี่ตัว ก่อนจะเลิกหาค่าของป้ายนั้น
#:
#: ★ ทำไมต้องจำกัด: บรรทัดที่ OCR รวมมาจากหลายคอลัมน์มีป้ายกับค่าของคนอื่นปนกัน
#:   เจอจริง (#28): "InUoice ID: 12102-002-0044557 POSD: E076... IaxInvoice.(ABB) UBI Included CRU-KFC 12102"
#:   ป้าย "Invoice" ตัวที่สองตามด้วย "(ABB) UBI Included" แล้วค่อยเจอ "12102" ซึ่งเป็นรหัสสาขา
#:   ถ้าไม่จำกัดระยะ ระบบจะเก็บรหัสสาขามาเป็นเลขอ้างอิง → ทุกใบของสาขานี้ชนกันหมด
_MAX_SKIP_TOKENS = 2

#: เลขผู้เสียภาษีไทยของนิติบุคคลมี 13 หลักเสมอ
#:
#: ★ ตาข่ายรับชั้นที่สอง (นอกเหนือจากการไม่ใส่ "tax id" ในรายการป้าย)
#:   เพราะ OCR อ่านป้ายเพี้ยนได้ เช่น "fAX 10:0105532021090" (#26) ซึ่งอาจหลุดผ่าน
#:   การเทียบป้ายไปได้ · เลข 13 หลักบนใบเสร็จแทบไม่มีอย่างอื่นนอกจากเลขภาษี
#:   ยอมทิ้งเลขอ้างอิง 13 หลักที่อาจมีจริง ดีกว่าปล่อยเลขภาษีเข้ามาเป็นลายนิ้วมือ
_TAX_ID_DIGITS = 13

#: แยกบรรทัดเป็นโทเคน — ตัดที่ช่องว่างและวงเล็บ แต่เก็บ - . # / ไว้ในโทเคน
#: เพราะเลขอ้างอิงจริงมีอักขระพวกนี้อยู่ข้างใน ("12102-002-0044557", "TRACE#071055")
_TOKEN_SPLIT = re.compile(r"[\s()\[\]:,]+")

#: ตัวเลขล้วนอย่างน้อย _MIN_DIGITS ตัว (ใช้ตอนแยกป้ายที่ติดกับค่า เช่น "INV713201824")
_FUSED_VALUE = re.compile(r"^([A-Za-z.#]{2,})(\d{%d,}.*)$" % _MIN_DIGITS)

#: อักขระที่ตัดทิ้งจากหัว-ท้ายค่า (เครื่องหมายวรรคตอนที่ติดมากับ OCR)
_VALUE_TRIM = " :.#-*=/"


def find_reference_codes(lines: list[str]) -> list[str]:
    """คืนเลขอ้างอิงทุกตัวที่เจอบนใบเสร็จ (ไม่ซ้ำ เรียงตามที่เจอ)

    ไม่เจอเลย → คืนลิสต์ว่าง ซึ่งเป็นเรื่องปกติ (ใบเสร็จบางแบบไม่มีเลขที่ให้อ่าน)
    การกันซ้ำจะไปพึ่งสัญญาณอื่นแทน (ยอด + วันที่ + เวลา) — ดู duplicate_check
    """
    found: list[str] = []
    for line in lines:
        for code in _codes_in_line(line):
            if code not in found:
                found.append(code)
    return found


def _codes_in_line(line: str) -> list[str]:
    tokens = [token for token in _TOKEN_SPLIT.split(line) if token]
    codes: list[str] = []

    for index, token in enumerate(tokens):
        label = _label_of(token)
        if label is None:
            continue

        # กรณีป้ายติดกับค่าในโทเคนเดียว: "TRACE#071055" · "INV713201824"
        fused = _value_fused_with_label(token)
        if fused:
            codes.append(fused)
            continue

        # กรณีป้ายกับค่าอยู่คนละโทเคน: "TRANS" "ID" "003646657141"
        value = _value_after(tokens, index)
        if value:
            codes.append(value)

    return codes


def _label_of(token: str) -> str | None:
    """โทเคนนี้ "เป็นป้าย" ของเลขอ้างอิงไหม — คืนชื่อป้ายมาตรฐาน หรือ None

    เทียบเฉพาะส่วนที่เป็นตัวอักษรหน้าสุดของโทเคน เพื่อให้ "TRACE#071055"
    และ "TRACE" ตัดสินได้เหมือนกัน
    """
    head = _alphabetic_head(token)
    if not head:
        return None

    normalized = head.lower().translate(_LABEL_LOOKALIKES)
    for label in _TRANSACTION_LABELS:
        if not label.isascii():
            if label in token:       # ป้ายไทยไม่ต้องแปลง lookalike
                return label
            continue
        # ★ ต้องตรงทั้งคำ ไม่ใช่แค่ "ขึ้นต้นเหมือนกัน"
        #   เจอจริง (#28): "Pepsi [Refill]" → OCR ได้ "Refii1" ซึ่งขึ้นต้นด้วย "ref"
        #   ระบบเลยนึกว่าเป็นป้ายเลขอ้างอิง แล้วเก็บเลขบรรทัดนั้นมาเป็นเลขอ้างอิง
        if normalized == label:
            return label
        # ★ ต้องยาวใกล้กันถึงจะเทียบแบบ "คล้ายพอ" — ไม่งั้นคำยาวๆ อย่าง "included"
        #   จะไปคล้ายกับ "invoice" จนจับผิด
        if abs(len(normalized) - len(label)) <= 2 and _looks_like(normalized, label):
            return label
    return None


def _alphabetic_head(token: str) -> str:
    """คำแรกที่เป็นตัวอักษรล้วนของโทเคน — "APPR.CODE#922535" → "APPR"

    ★ ตัดที่จุด/# โดยตั้งใจ: ป้ายจริงคือคำแรก ส่วนที่ตามหลังเป็นคำขยาย
      ถ้าเอาทั้ง "APPR.CODE" ไปเทียบ จะไม่ตรงกับป้าย "appr" ที่เรารู้จัก
      และรูปอีกมุมของสลิปใบเดียวกันที่ OCR อ่านได้ "APPR CODE#922535" (มีช่องว่าง)
      จะได้ผลไม่ตรงกัน — เลขอ้างอิงใช้กันซ้ำไม่ได้ทั้งที่อ่านตัวเลขถูกทั้งคู่
    """
    head = re.match(r"^[A-Za-zก-๙]+", token)
    return head.group(0) if head else ""


def _looks_like(candidate: str, label: str) -> bool:
    if len(label) < 4:               # ป้ายสั้น ("ref", "inv") ต้องตรงเป๊ะ ไม่งั้นชนมั่ว
        return False
    return SequenceMatcher(None, candidate, label).ratio() >= _LABEL_FUZZY_THRESHOLD


def _value_fused_with_label(token: str) -> str | None:
    """แยกค่าออกจากป้ายที่ติดกัน — "TRACE#071055" → "071055" """
    match = _FUSED_VALUE.match(token)
    if not match:
        return None
    return _clean_value(match.group(2))


def _value_after(tokens: list[str], label_index: int) -> str | None:
    """หาค่าของป้ายจากโทเคนถัดไป — ข้ามโทเคนที่ไม่มีตัวเลขได้ไม่เกิน _MAX_SKIP_TOKENS ตัว"""
    skipped = 0
    for token in tokens[label_index + 1:]:
        value = _clean_value(token) if any(char.isdigit() for char in token) else None
        if value:
            return value

        # ★ โทเคนที่ "มีตัวเลขแต่ใช้เป็นเลขอ้างอิงไม่ได้" ต้องข้ามต่อ ไม่ใช่เลิกหา
        #   เจอจริง (#1): OCR อ่าน "Invoice ID:" เป็น "Inuoice 10:" — ตัว ID กลายเป็นเลข 10
        #   ถ้าเลิกหาตรงนั้น เลขอ้างอิงจริงที่อยู่ถัดไปจะหายทั้งใบ
        skipped += 1
        if skipped > _MAX_SKIP_TOKENS:
            return None
    return None


def _clean_value(raw: str) -> str | None:
    """ทำความสะอาดค่า + ตรวจว่าใช้เป็นเลขอ้างอิงได้จริงไหม"""
    value = raw.strip(_VALUE_TRIM)
    # ตัดคำที่ติดมาข้างหน้าตัวเลขออก — เจอจริง (#21): "APPR CODE#922535" ถูกหั่นเป็น
    # "APPR" + "CODE#922535" ทำให้ค่าที่ได้ติดคำว่า CODE มาด้วย แล้วไม่ตรงกับอีกรูป
    # ที่อ่านได้ "APPR.CODE#922535" (ป้ายติดกับค่าในโทเคนเดียว)
    fused = _FUSED_VALUE.match(value)
    if fused:
        value = fused.group(2).strip(_VALUE_TRIM)
    digits = [char for char in value if char.isdigit()]

    if len(digits) < _MIN_DIGITS:
        return None
    if len(digits) == _TAX_ID_DIGITS and len(value) == _TAX_ID_DIGITS:
        return None  # เลขผู้เสียภาษี — เหมือนกันทุกใบของร้านนี้ (ดูหัวไฟล์)
    return value
