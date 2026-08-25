"""เทส app/receipt_data/line_items.py

★ บรรทัดในเทสนี้คือ "ข้อความที่ OCR อ่านได้จริง" จากใบเสร็จในชุดทดสอบ
  มีตัวอักษรเพี้ยนเต็มไปหมดโดยตั้งใจ (Total → Tota114900, VAT → UAT, Cash → LCash)
  ห้ามแก้ให้ "ถูกต้อง" เพราะจะทำให้เทสไม่ได้ทดสอบสิ่งที่ระบบเจอจริง

เทสสองด้านที่ตรงข้ามกัน:
    ต้องอ่านได้      — รายการสินค้าจริงต้องออกมาครบ
    ★ ต้องไม่อ่านเกิน — ข้อความโปรโมชัน/เงินทอน/รหัส ต้องไม่กลายเป็นสินค้า
                        (ถ้าเกิน ผลรวมราคาจะเพี้ยน แล้วการตรวจด้วยคณิตศาสตร์ใช้ไม่ได้)
"""
from app.receipt_data.line_items import LineItem, find_line_items, items_match_total


# ═══════════════════════════════════════════
# อ่านรายการสินค้าได้ถูก
# ═══════════════════════════════════════════

def test_dq_receipt_two_items():
    """ใบ DQ #4 — โครงสร้างตรงไปตรงมาที่สุดในชุดทดสอบ"""
    lines = [
        "Host: DO CASHIER 06/06/2026",
        "Q#6 5:13 PM",
        "10231",
        "CONE(L) 20",
        "BZ OUL MINT CHIP BROWN S 59",
        "Subtotal 79",
        "Order Total 79",
    ]
    assert find_line_items(lines, total_amount=79.0) == [
        LineItem("CONE(L)", 20.0),
        LineItem("BZ OUL MINT CHIP BROWN S", 59.0),
    ]


def test_kfc_set_menu_items_without_price():
    """★ ใบ KFC #1 — ชุดเซ็ตพิมพ์ราคารวมบรรทัดแรก แล้วไล่ชื่อของในชุดโดยไม่มีราคา

    รายการที่ไม่มีราคาต้องถูกเก็บด้วย (เป็นข้อมูลของสินค้าที่ซื้อจริง)
    ไม่ใช่ทิ้งเพราะ "หาราคาไม่เจอ"
    """
    lines = [
        "#2330 6:15 PM",
        "20330",
        "B0X A11 Easy 149.00",
        "Crispystrip",
        "Nuggets",
        "Chicken Pop",
        "Rifrench fries",
        "Pepsi Refii",
        "Take Away Tota114900",
    ]
    items = find_line_items(lines, total_amount=149.0)

    assert len(items) == 6
    assert items[0] == LineItem("B0X A11 Easy", 149.0)
    assert all(item.price is None for item in items[1:])


def test_thai_item_with_trailing_unit_character():
    """ใบ V-Square — OCR อ่านตัวอักษรเกินมาท้ายราคา ("35.00 น")"""
    lines = [
        "ราคารวมภาษีมูลค่าเพิ่มแล้ว #ยกเว้น",
        "กระตายตาะแA4 200L035 35.00 น",
        "ยอตสทธิ 35.00",
    ]
    items = find_line_items(lines, total_amount=35.0)

    assert len(items) == 1
    assert items[0].price == 35.0


def test_stops_at_card_balance_on_food_court_slip():
    """★ สลิปศูนย์อาหาร BigC — OCR เชื่อมคำเป็น "CardBalance"

    ถ้าบังคับให้เจอคำว่า "Balance" แบบคำเต็ม จะหาจุดจบไม่เจอทั้งใบ
    แล้วไม่ได้รายการอาหารเลยสักรายการ
    """
    lines = [
        "TAX 1D 0107536000633",
        "ซ้จวคาก 10.00",
        "CardBalance AMT 300.00",
        "Sale Anmount AMT 75.00",
    ]
    items = find_line_items(lines, total_amount=75.0)

    assert [item.name for item in items] == ["ซ้จวคาก"]


# ═══════════════════════════════════════════
# ★ ต้องไม่อ่านเกิน
# ═══════════════════════════════════════════

def test_promo_text_in_header_is_not_an_item():
    """★★ กับดักที่ทำให้ต้องไล่ "ขึ้น" จากยอดรวม แทนที่จะไล่ลงจากหัวใบ

    ข้อความโปรโมชันบนหัวใบ DQ มีทั้งข้อความและตัวเลข หน้าตาเหมือนรายการสินค้าเป๊ะ
    ถ้าไล่ลงจากหัวใบ บรรทัดนี้จะกลายเป็น "สินค้าชื่อ ...เค้กใหญ่ 8 นิ้ว ราคา 30 บาท"
    """
    lines = [
        "TAX INV0ICE (ABB) : 23191",
        "www.talktoDQthailand.com",
        "รับมสิทธิสานลดชื้อเศกใหญ 8 นี้ำ 30 มาท",
        "MINOR DQ LIHITED",
        "TAX I0: 0105525046201",
        "10231",
        "CONE(L) 20",
        "Subtotal 20",
    ]
    assert find_line_items(lines, total_amount=20.0) == [LineItem("CONE(L)", 20.0)]


def test_thai_word_for_rights_is_not_mistaken_for_net_total():
    """★ คำว่า "สิทธิ" (รับสิทธิ/สิทธิพิเศษ) มีชิ้นส่วนเดียวกับ "ยอดสุทธิ"

    เคยจับแค่ชิ้น "ทธิ" แล้วพัง — ระบบตัดจบส่วนรายการตั้งแต่บรรทัดโปรโมชันหัวใบ
    แล้วเก็บข้อความโปรโมชันมาเป็นสินค้าแทน
    """
    lines = [
        "รับสิทธิส่วนลดซื้อเค้กใหญ่ 8 นิ้ว 30 บาท",
        "CONE(L) 20",
        "ยอดสุทธิ 20",
    ]
    assert find_line_items(lines, total_amount=20.0) == [LineItem("CONE(L)", 20.0)]


def test_cashier_line_does_not_end_the_item_section():
    """★ "Host: DQ CASHIER" มีคำว่า cash ซ่อนอยู่ใน CASHIER

    เคยจับแบบชิ้นส่วนของคำแล้วพัง — ระบบตัดจบส่วนรายการตั้งแต่บรรทัดหัวใบ
    แล้วไม่ได้สินค้าเลย
    """
    lines = ["Host: DQ CASHIER", "OREO SUNDAE 39", "Subtotal 39"]
    assert find_line_items(lines, total_amount=39.0) == [LineItem("OREO SUNDAE", 39.0)]


def test_cash_and_change_lines_are_not_items():
    """★ ใบ KFC #27 — OCR อ่าน "Cash" เป็น "LCash" คำเต็มจับไม่ได้

    ถ้าปล่อยผ่าน บรรทัดเงินสด/เงินทอนจะกลายเป็นสินค้า แล้วผลรวมราคาเพี้ยน
    """
    lines = ["KreanCup Choco 35.00", "LCash #40.00", "Change B500", "Order Total 35.00"]
    items = find_line_items(lines, total_amount=35.0)

    assert [item.name for item in items] == ["KreanCup Choco"]


def test_quantity_prefix_is_not_a_price():
    """★ ราคาต้องอยู่ท้ายบรรทัดเท่านั้น — คอลัมน์ราคาบนใบเสร็จชิดขวาเสมอ

    เจอจริงบนใบ KFC: "[2] Wingz Zabb" ถูกอ่านเป็น "[21 Wingz Zabb"
    เวอร์ชันแรกหาเลขทั้งบรรทัด เลยได้สินค้าราคา 21 บาททั้งที่รายการนี้ไม่มีราคา
    """
    lines = ["COB 449.00", "[21 Wingz Zabb", "HSPiece_(7 @0.00)", "Eat In Total 528.00"]
    items = find_line_items(lines, total_amount=528.0)

    assert items[0].price == 449.0
    assert all(item.price is None for item in items[1:])


def test_check_number_is_not_a_price():
    """เลขที่เช็คที่ต่อท้ายชื่อสินค้า ต้องไม่กลายเป็นราคา (มากกว่ายอดรวมทั้งใบ)"""
    lines = ["NewSuk Jai 20299", "Eat In Total 528.00"]
    items = find_line_items(lines, total_amount=528.0)

    assert items == [LineItem("NewSuk Jai", None)]


def test_pure_number_line_is_skipped_not_treated_as_item():
    """เลขที่บิล/เลขคิวที่ยืนเดี่ยวกลางกลุ่มรายการ ต้องข้ามไป ไม่ใช่หยุดอ่าน"""
    lines = ["10243", "OREO SUNDAE 39", "Subtotal 39"]
    assert find_line_items(lines, total_amount=39.0) == [LineItem("OREO SUNDAE", 39.0)]


def test_no_total_line_returns_nothing():
    """หาจุดจบไม่เจอ = ไม่รู้ว่าส่วนรายการอยู่ตรงไหน → ไม่เดา"""
    assert find_line_items(["CONE(L) 20", "BZ OUL MINT 59"], total_amount=79.0) == []


def test_empty_input():
    assert find_line_items([]) == []


# ═══════════════════════════════════════════
# ★ ผลรวมราคา = ยอดรวม (หลักฐานทางคณิตศาสตร์)
# ═══════════════════════════════════════════

def test_items_match_total_when_sum_is_right():
    """ใบ KFC 528 จริง: 449 + 20 + 59 = 528"""
    items = [LineItem("New Suk Jai", 449.0), LineItem("fries", 20.0), LineItem("roll", 59.0)]
    assert items_match_total(items, 528.0)


def test_items_do_not_match_when_a_price_was_misread():
    """★ อ่านราคาผิดตัวเดียว สมการก็ไม่ลงตัว — นี่คือประโยชน์ทั้งหมดของกฎนี้"""
    items = [LineItem("New Suk Jai", 449.0), LineItem("fries", 20.0), LineItem("roll", 60.0)]
    assert not items_match_total(items, 528.0)


def test_items_without_prices_are_not_counted_as_proof():
    """ชุดเซ็ตที่ของในชุดไม่มีราคา — ราคารายการแรกต้องเท่ากับยอดรวมเอง"""
    items = [LineItem("BOX All Easy", 149.0), LineItem("CrispyStrip", None)]
    assert items_match_total(items, 149.0)


def test_no_priced_item_is_not_proof():
    """★ ไม่มีหลักฐาน ต้องตอบว่า "ยืนยันไม่ได้" ไม่ใช่ "ผ่าน" """
    assert not items_match_total([LineItem("อะไรสักอย่าง", None)], 100.0)
    assert not items_match_total([], 100.0)
