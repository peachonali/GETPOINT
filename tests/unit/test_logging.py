"""เทส app/observability/logging.py

ทำไมไฟล์นี้สำคัญกว่าที่คิด:
    การ mask คือ security control ที่ "พังแบบเงียบ" — ถ้าเลิกทำงาน credential
    จะไหลลง log โดยไม่มีใครรู้ ไม่มี error ไม่มีอาการ กว่าจะรู้ก็ตอนหลุดแล้ว
    เทสชุดนี้คือสิ่งเดียวที่จะส่งเสียงแทน

หมายเหตุ: mask_text / safe_url เป็น pure function เทสได้ตรงๆ ไม่ต้องมี logger
"""
import logging

from app.observability.logging import (
    JsonLogFormatter,
    get_logger,
    log_context,
    mask_text,
    safe_url,
)

#: URL จริงที่ loga บังคับให้ยิง — token/เบอร์ลูกค้าอยู่ใน query string หมด
LOGA_URL = (
    "https://api.loga.app/api/points/add_customer_point"
    "?token=SECRET123&uuid=4510471&cuid=0812345678&cost=250&formula_id=7"
)


# ═══════════════════════════════════════════
# mask_text — ต้องปิดบัง
# ═══════════════════════════════════════════

def test_mask_token_in_query_string():
    assert "SECRET123" not in mask_text(LOGA_URL)


def test_mask_password_and_otp_in_json():
    masked = mask_text('{"password": "p@ssw0rd", "otp": "483920"}')
    assert "p@ssw0rd" not in masked
    assert "483920" not in masked


def test_mask_authorization_header():
    assert "eyJhbGciOi" not in mask_text("Authorization: Bearer eyJhbGciOi.abc123")


def test_mask_thai_mobile_number():
    """PDPA — เบอร์คือข้อมูลส่วนบุคคล เหลือหัว 3 ท้าย 2 พอไว้เทียบเคส แต่โทรออกไม่ได้"""
    assert mask_text("ลูกค้า 0812345678 สมัคร") == "ลูกค้า 081*****78 สมัคร"
    assert "812345678" not in mask_text("+66812345678")


# ═══════════════════════════════════════════
# mask_text — ต้อง "ไม่" ปิดบังของที่ต้องใช้ debug
# ═══════════════════════════════════════════

def test_keep_non_secret_values():
    """mask เกินจำเป็น = log ไร้ประโยชน์ ซึ่งแย่พอกับ log ที่รั่ว"""
    masked = mask_text(LOGA_URL)
    assert "cost=250" in masked
    assert "formula_id=7" in masked
    assert "add_customer_point" in masked


def test_plain_text_untouched():
    assert mask_text("อ่านใบเสร็จสำเร็จ 3 รายการ") == "อ่านใบเสร็จสำเร็จ 3 รายการ"


# ═══════════════════════════════════════════
# safe_url — ชั้นที่ 1 (ตั้งใจตัด)
# ═══════════════════════════════════════════

def test_safe_url_drops_whole_query_string():
    assert safe_url(LOGA_URL) == "https://api.loga.app/api/points/add_customer_point"


# ═══════════════════════════════════════════
# formatter — ชั้นที่ 2 (ตาข่าย) + บริบทติดทุกบรรทัด
# ═══════════════════════════════════════════

def _format(msg: str, exc_info=None, **extra) -> str:
    """สร้าง log 1 บรรทัดตรงๆ จาก formatter (ไม่ต้องพึ่ง handler/stdout)"""
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__,
        lineno=1, msg=msg, args=(), exc_info=exc_info,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return JsonLogFormatter().format(record)


def test_extra_field_is_masked():
    """คนเรียกเผลอ log URL เต็มผ่าน extra — ตาข่ายต้องรับไว้"""
    assert "SECRET123" not in _format("ยิง loga", url=LOGA_URL)


def test_traceback_is_masked():
    """เคสที่ safe_url ช่วยไม่ได้เลย เพราะไม่มีใครเรียกมัน — พบตอนเทสจริง"""
    try:
        raise ValueError(f"loga ปฏิเสธ: {LOGA_URL}")
    except ValueError as exc:
        line = _format("ส่งแต้มไม่สำเร็จ", exc_info=(type(exc), exc, exc.__traceback__))
    assert "SECRET123" not in line
    assert "0812345678" not in line


def test_context_is_attached_to_every_line():
    with log_context(job_id="j-123", tenant_id="v-club"):
        line = _format("เริ่มประมวลผล")
    assert '"job_id": "j-123"' in line
    assert '"tenant_id": "v-club"' in line


def test_context_nests_and_is_released():
    with log_context(job_id="j-123"):
        with log_context(receipt_id="r-9"):
            inner = _format("ocr เสร็จ")
        after_inner = _format("ส่งแต้ม")
    outside = _format("จบงาน")

    assert '"receipt_id": "r-9"' in inner and '"job_id": "j-123"' in inner
    assert "r-9" not in after_inner, "ออกจากบล็อกในแล้วต้องไม่เหลือ receipt_id"
    assert "j-123" not in outside, "ออกจากบล็อกนอกแล้วต้องไม่เหลือ job_id"


def test_thai_text_is_readable_not_escaped():
    """ถ้าไทยกลายเป็น \\uXXXX คนอ่าน log จะอ่านไม่ออก"""
    assert '"msg": "อ่านใบเสร็จ"' in _format("อ่านใบเสร็จ")


def test_get_logger_returns_named_logger():
    assert get_logger("app.external.loga_client").name == "app.external.loga_client"


def test_extra_key_colliding_with_logrecord_does_not_crash():
    """logging มาตรฐานโยน KeyError ถ้า extra ใช้ชื่อ msg/name/module/args ฯลฯ
    = log ผิดบรรทัดเดียวทำให้ระบบล้ม · เจอของจริงตอนเขียน loga_client
    ระบบต้องเปลี่ยนชื่อให้เอง ไม่ใช่พังใส่หน้าลูกค้า"""
    logger = get_logger("test.collision")
    logger.addHandler(logging.NullHandler())

    logger.warning("CRM ปฏิเสธ", extra={"msg": "not found", "name": "x", "module": "y"})


def test_colliding_extra_value_is_kept_under_renamed_key():
    """เปลี่ยนชื่อแล้วต้องยังเห็นค่าเดิมใน log — ไม่ใช่กลืนทิ้งเงียบๆ"""
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="CRM ปฏิเสธ", args=(), exc_info=None,
    )
    setattr(record, "msg_", "not found")

    assert '"msg_": "not found"' in JsonLogFormatter().format(record)
