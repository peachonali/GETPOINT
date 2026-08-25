"""เทส app/receipt_data/reference_code.py

★ บรรทัดในเทสนี้ส่วนใหญ่คือ "ข้อความที่ OCR อ่านได้จริง" จากใบเสร็จในชุดทดสอบ
  ไม่ใช่ข้อความที่พิมพ์ให้สวย — จึงมีตัวอักษรเพี้ยนอยู่เต็มไปหมดโดยตั้งใจ
  (เช่น Invoice → Inuoice, ID → 10, VAT → UAT)
  ห้ามแก้ให้ "ถูกต้อง" เพราะนั่นจะทำให้เทสไม่ได้ทดสอบสิ่งที่ระบบเจอจริง

หน้าที่ของไฟล์ที่เทส: หาเลขที่ "ไม่ซ้ำข้ามใบ" มาใช้กันแต้มซ้ำ
    ต้องเก็บ    — เลขของธุรกรรมนี้ (Invoice ID / TRANS ID / Tax INV)
    ★ ต้องไม่เก็บ — เลขของร้าน/เครื่อง/บัตร (TAX ID / POS ID / MER#)
                    เพราะเหมือนกันทุกใบของร้านนั้น → ทำให้ใบคนละใบกลายเป็นใบซ้ำ
"""
from app.receipt_data.reference_code import find_reference_codes


# ═══════════════════════════════════════════
# ต้องเก็บ — เลขของธุรกรรม
# ═══════════════════════════════════════════

def test_kfc_invoice_id():
    """ใบ KFC #1 — OCR อ่าน "Invoice ID:" เป็น "Inuoice 10:" (v→u, ID→10)"""
    assert find_reference_codes(["Inuoice 10: 12102-002-0044557"]) == ["12102-002-0044557"]


def test_kfc_invoice_id_from_the_other_photo():
    """ใบเดียวกัน อีกมุม — OCR รวมหลายคอลัมน์มาไว้บรรทัดเดียว

    ต้องได้เลขเดียวกับรูปแรก ไม่งั้นใบเดียวกันกลายเป็นคนละใบ = ได้แต้มสองเท่า
    """
    line = (
        "InUoice ID: 12102-002-0044557 POSD: E0760000030009 IaxInvoice.(ABB) UBI Included "
        "CRU-KFC 12102 (KFC-BIB C NAKORNSAVAN) TAX 10: 0105532021090"
    )
    assert "12102-002-0044557" in find_reference_codes([line])


def test_bank_slip_trans_id():
    """สลิปธนาคารกรุงเทพ — เลขที่อ่านได้ตรงกันทั้งสองรูปในชุดทดสอบ"""
    assert "003646657141" in find_reference_codes(["TRANS ID. 003646657141"])


def test_label_fused_with_value():
    """"TRACE#071055" — ป้ายติดกับค่าในโทเคนเดียว ต้องแยกออกได้"""
    codes = find_reference_codes(["STAN#071650 TRACE#071055"])
    assert set(codes) == {"071650", "071055"}


def test_label_split_from_value_by_ocr():
    """★ ใบ #21: "APPR.CODE#922535" ถูก OCR หั่นเป็น "APPR CODE#922535"

    ถ้าไม่ตัดคำว่า CODE ออก ค่าที่ได้จะเป็น "CODE#922535" ซึ่งไม่ตรงกับอีกรูป
    ที่อ่านได้ "922535" → เลขอ้างอิงใช้การไม่ได้ทั้งที่อ่านตัวเลขมาถูกทั้งคู่
    """
    assert "922535" in find_reference_codes(["BATCH#000314 APPR CODE#922535"])
    assert "922535" in find_reference_codes(["BATCH#000314 APPR.CODE#922535"])


def test_bigc_tax_invoice_number():
    """BigC ศูนย์อาหาร — ป้าย "Tax INV" ติดกับตัวเลข"""
    assert "713201824" in find_reference_codes(["T0713 25Tax INV713201824"])


def test_dq_tax_invoice_abb():
    """DQ — "TAX INV0ICE (ABB) : 23191" (ตัว O เป็นเลข 0)"""
    assert "23191" in find_reference_codes(["TAX INV0ICE (ABB) : 23191"])


# ═══════════════════════════════════════════
# ★ ต้องไม่เก็บ — เลขที่เหมือนกันทุกใบของร้านนั้น
# ═══════════════════════════════════════════

def test_tax_id_is_not_a_reference_code():
    """★ เลขผู้เสียภาษี 13 หลัก เหมือนกันทุกใบของร้าน

    ถ้าเก็บมา ระบบจะมองว่า "ซื้อ KFC 149 บาทเมื่อวานกับวันนี้" เป็นใบเดียวกัน
    แล้วปฏิเสธแต้มของวันนี้ — ลูกค้าเสียแต้มที่ควรได้
    """
    assert find_reference_codes(["TAX ID: 0105532021090"]) == []
    assert find_reference_codes(["fAX 10:0105532021090"]) == []   # ป้ายเพี้ยน ยังต้องไม่หลุด


def test_pos_id_is_not_a_reference_code():
    """เลขเครื่องแคชเชียร์ — ใบ KFC 149 กับ 528 ใช้ POS ID เดียวกัน (E076000003A0009)"""
    assert find_reference_codes(["POS ID: E076000003A0009"]) == []


def test_merchant_id_on_bank_slip_is_not_a_reference_code():
    """MER# = รหัสร้านค้าฝั่งธนาคาร เหมือนกันทุกสลิปของร้านนั้น"""
    assert find_reference_codes(["MER#000002206415630"]) == []


def test_card_number_is_not_a_reference_code():
    """เลขบัตรศูนย์อาหาร ผูกกับใบบัตร ไม่ใช่กับการซื้อครั้งนี้"""
    assert find_reference_codes(["Card No:3210019969783 AMT 10.00"]) == []


def test_restaurant_id_is_not_a_reference_code():
    assert find_reference_codes(["Restaurant ID 41287"]) == []


def test_refill_is_not_mistaken_for_a_reference_label():
    """★ ใบ #28: "Pepsi [Refill]" ถูกอ่านเป็น "Refii1"

    ขึ้นต้นด้วย "ref" เหมือนป้าย REF# ของสลิปธนาคาร ถ้าเทียบแบบ "ขึ้นต้นเหมือนกัน"
    ระบบจะเก็บตัวเลขที่อยู่ถัดไปในบรรทัดมาเป็นเลขอ้างอิงมั่วๆ
    """
    assert find_reference_codes(["Pepsi (Refii1) RiFrench fries 20330"]) == []


def test_invoice_label_without_value_yields_nothing():
    """หัวใบ KFC มีคำว่า Invoice แต่ตามด้วย "(ABB) VAT Included" ไม่ใช่เลข"""
    assert find_reference_codes(["Iax Invgice (ABB) VBI Included"]) == []


def test_short_numbers_are_ignored():
    """ยอดเงิน/จำนวนชิ้น/เงินทอน ต้องไม่กลายเป็นเลขอ้างอิง"""
    assert find_reference_codes(["Order Total 79", "Cash 100", "Change 21"]) == []


# ═══════════════════════════════════════════
# พฤติกรรมทั่วไป
# ═══════════════════════════════════════════

def test_no_duplicate_codes():
    line = "TRANS ID. 003646657141"
    assert find_reference_codes([line, line]) == ["003646657141"]


def test_empty_input():
    assert find_reference_codes([]) == []
