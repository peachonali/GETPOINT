"""เทส app/merchant/known_merchant.py + merchant_resolver.py

★ ข้อความในเทสนี้คือสิ่งที่ OCR อ่านได้จริงจากใบเสร็จในชุดทดสอบ (มีตัวอักษรเพี้ยน)

หน้าที่ของสองไฟล์นี้: ตอบให้ได้ว่า "ใบนี้มาจากร้านไหน" ด้วย **รหัสร้านที่คงที่**
ไม่ใช่ชื่อร้านที่ OCR อ่านได้ ซึ่งอ่านได้ไม่คงที่แม้แต่ระหว่างสองรูปของใบเดียวกัน

ทิศทางของความผิดพลาด: ★ ตอบผิดร้าน แย่กว่า ตอบว่าไม่รู้จัก
เพราะตอบผิดร้าน = ใช้ template ผิด = ดึงค่าผิด = ให้แต้มผิดทั้งร้าน (CONTEXT ข้อ 4)
"""
from app.merchant.known_merchant import identify
from app.merchant.merchant_resolver import resolve


# ═══════════════════════════════════════════
# จับจากเลขผู้เสียภาษี — สัญญาณหลัก
# ═══════════════════════════════════════════

def test_identify_by_tax_id():
    """ใบ KFC #1 — "TAX ID:" ถูกอ่านเป็น "TAX 10:" แต่ตัวเลขอ่านถูก"""
    merchant = identify(["CRG-KFC 12IO2 (KEC-BIO C NAKORNSAVAN) TAX 10: 0105532021090"])
    assert merchant is not None
    assert merchant.code == "kfc"


def test_identify_by_tax_id_when_shop_name_is_unreadable():
    """★ นี่คือเหตุผลทั้งหมดที่ใช้เลขภาษีเป็นสัญญาณหลัก

    บรรทัดนี้คือสิ่งที่ OCR อ่านได้จากใบ KFC อีกมุมหนึ่ง — ไม่มีคำว่า KFC เลย
    แต่เลขภาษียังอ่านได้ครบ
    """
    merchant = identify(["fAX 10:0105532021090", "Host: : Prapapan #2330 BOX AI1 Easy"])
    assert merchant is not None
    assert merchant.code == "kfc"


def test_tax_id_with_spaces_inserted_by_ocr():
    """OCR แทรกช่องว่างกลางเลขได้ — ต้องยังจับได้"""
    merchant = identify(["TAX ID: 0105525 046201"])
    assert merchant is not None
    assert merchant.code == "dq"


# ═══════════════════════════════════════════
# จับจากคำเฉพาะ — ใช้เมื่ออ่านเลขภาษีไม่ได้
# ═══════════════════════════════════════════

def test_identify_by_keyword_when_tax_id_unreadable():
    """ใบ KFC #3 — เลขภาษีถูกอ่านติดกับคำว่า TAX จนเพี้ยน"""
    merchant = identify(["CRG-KFC 12102. (KFC-BIO C NAKORNSAVAN) TAX 100105532021090"])
    assert merchant is not None
    assert merchant.code == "kfc"


def test_keyword_survives_zero_for_letter_o():
    """ใบ BigC #19 — "FOODPark" ถูกอ่านเป็น "F0ODPark" (ตัว O เป็นเลขศูนย์)"""
    merchant = identify(["****+*}*****F0ODPark*+****+*x*", "NAKHONSAWANBRANCH"])
    assert merchant is not None
    assert merchant.code == "bigc-foodpark"


def test_keyword_survives_one_missing_letter():
    """ใบ Pizza #18 — "THE PIZZA" ถูกอ่านเป็น "emTHE PIZA" (z หายไปตัว)"""
    merchant = identify(["emTHE PIZZA", "order online www.1112.com"])
    assert merchant is not None
    assert merchant.code == "the-pizza-company"


# ═══════════════════════════════════════════
# ★ ต้องไม่จับผิดร้าน
# ═══════════════════════════════════════════

def test_kfc_inside_big_c_is_not_big_c():
    """★★ กับดักที่สำคัญที่สุดของไฟล์นี้

    ใบ KFC และ DQ ในชุดทดสอบพิมพ์ที่ตั้งสาขาว่า "BIG C NAKORNSAWAN"
    ถ้าใช้คำว่า "big c" เป็นคำเฉพาะของร้าน BigC ใบ KFC ทุกใบจะถูกจับเป็น BigC
    → ใช้ template ผิดร้าน → ดึงค่าผิด → ลูกค้าทั้งร้านได้แต้มผิด

    ★ เทสนี้จงใจให้ "เลขภาษีอ่านไม่ออก" เพื่อบังคับให้ระบบไปใช้ทางคำเฉพาะ
      ถ้าปล่อยให้เลขภาษีอ่านออก ทางนั้นจะชนะก่อนเสมอ แล้วเทสจะเขียวโดยไม่ได้
      ทดสอบสิ่งที่ตั้งใจเลย (เจอตอนทดลองทำลายโค้ดว่าเทสมีเขี้ยวไหม)
      รูปแบบบรรทัดมาจากของจริง (#3) ที่ "TAX ID:" ไปติดกับตัวเลขจนอ่านเลขไม่ได้
    """
    merchant = identify(["CRG-KFC 12102 (KFC-BIG C NAKORNSAWAN) TAX 1D01055-32021O90"])
    assert merchant is not None
    assert merchant.code == "kfc"


def test_dq_inside_big_c_is_not_big_c():
    """เช่นเดียวกับ KFC — เลขภาษีอ่านไม่ออก ต้องไม่ตกไปเป็นร้าน BigC"""
    merchant = identify(["MINOR DQ LIMITED", "DQ_BIG C NAKHONSAWAN", "TAX I0 O1O5525O462O1"])
    assert merchant is not None
    assert merchant.code == "dq"


def test_mall_name_alone_identifies_nothing():
    """★★ "BIG C NAKORNSAWAN" คือ "ที่ตั้งสาขา" ไม่ใช่ชื่อร้าน

    ร้าน KFC / DQ / Pizza ในห้างเดียวกันพิมพ์บรรทัดนี้บนใบเสร็จของตัวเองทุกใบ
    ถ้าเอาคำนี้เป็นคำเฉพาะของร้าน BigC ใบของร้านอื่นที่อ่านชื่อร้านตัวเองไม่ออก
    จะตกไปเป็นร้าน BigC → ใช้ template ผิดร้าน → ลูกค้าทั้งร้านได้แต้มผิด

    ★ ตอบ "ไม่รู้จัก" ถูกต้องกว่าเดา — เจอตอนทดลองทำลายโค้ดว่าเทสมีเขี้ยวไหม
      (เทสเดิมเขียวเพราะลำดับในทะเบียนบังเอิญช่วยไว้ ไม่ใช่เพราะเลือกคำถูก)
    """
    assert identify(["BIG C NAKORNSAWAN", "THANK YOU", "Total 149.00"]) is None


def test_similar_but_different_word_does_not_match():
    """★ เทียบแบบ "คล้ายพอ" ต้องไม่หลวมจนคำอื่นชนได้

    "kfe" ต่างจาก "kfc" แค่ตัวเดียว แต่ต้องไม่ถูกจับเป็น KFC
    (คำสั้นที่ต่างกัน 1 ตัว ได้คะแนนแค่ 0.67 ซึ่งต่ำกว่าเกณฑ์ 0.85)
    """
    assert identify(["kfe chicken shop", "รวม 100"]) is None


def test_unknown_shop_returns_none():
    """★ ไม่รู้จักต้องตอบ None ไม่ใช่เดาร้านที่ใกล้เคียงที่สุด"""
    assert identify(["ร้านลุงสมชาย", "TAX ID: 9999999999999", "รวม 100.00"]) is None


def test_empty_input():
    assert identify([]) is None


# ═══════════════════════════════════════════
# merchant_resolver — จุดตัดสินใจ
# ═══════════════════════════════════════════

def test_resolver_uses_registry_name_not_ocr_text():
    """★ ชื่อที่ลูกค้าเห็นต้องมาจากทะเบียน ไม่ใช่ข้อความมั่วๆ ที่ OCR อ่านได้"""
    resolved = resolve(["CRG-KFC 12IO2 (KEC-BIO C NAKORNSAVAN) TAX 10: 0105532021090"])

    assert resolved.code == "kfc"
    assert resolved.display_name == "KFC"
    assert resolved.is_known


def test_resolver_keeps_raw_name_for_review():
    """ชื่อดิบต้องเก็บไว้ — ไว้ให้คนดูตอนขึ้นทะเบียนร้านใหม่ และไว้ debug"""
    resolved = resolve(["ร้านลุงสมชาย", "รวมทั้งสิ้น 100.00"])
    assert resolved.raw_name is not None


def test_resolver_never_raises_for_unknown_shop():
    """★ ร้านที่ไม่รู้จักไม่ใช่ความผิดพลาด

    ลูกค้ายังต้องได้แต้มจากยอดเงินที่อ่านได้ แม้เรายังไม่มี template ของร้านนั้น
    """
    resolved = resolve(["ร้านที่ไม่เคยเจอ", "รวม 50"])

    assert resolved.code is None
    assert not resolved.is_known
    assert resolved.display_name  # ต้องมีชื่อให้แสดงเสมอ ไม่ใช่ค่าว่าง


def test_resolver_handles_nothing_readable():
    resolved = resolve([])
    assert resolved.code is None
    assert resolved.display_name == "ไม่ทราบร้าน"
