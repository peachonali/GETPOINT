"""เทส app/member/phone_normalize.py

เบอร์คือกุญแจเชื่อมลูกค้า — normalize ที่พลาดแปลว่าลูกค้าคนเดียวแตกเป็นหลายตัวตน
เทสจึงเน้น "รูปต่างกันของเบอร์เดียวกันต้องได้ผลเดียวกัน" เป็นพิเศษ
"""
import pytest

from app.member.phone_normalize import normalize_phone
from app.reliability.errors import InputValidationError

CANONICAL = "0812345678"


# ═══════════════════════════════════════════
# รูปต่างๆ ของเบอร์เดียวกัน → ต้องได้ค่าเดียว
# ═══════════════════════════════════════════

@pytest.mark.parametrize("raw", [
    "0812345678",
    "+66812345678",
    "66812345678",
    "081-234-5678",
    "081 234 5678",
    "081.234.5678",
    "(081) 234-5678",
    "  0812345678  ",
    "+66 81 234 5678",
    "+660812345678",   # คนกรอกเกิน: ใส่ทั้ง +66 และ 0
])
def test_various_forms_map_to_same_canonical(raw):
    assert normalize_phone(raw) == CANONICAL


def test_all_mobile_prefixes_accepted():
    """มือถือไทยปัจจุบันขึ้น 06 / 08 / 09 — ต้องรับครบ"""
    assert normalize_phone("0612345678") == "0612345678"
    assert normalize_phone("0912345678") == "0912345678"


# ═══════════════════════════════════════════
# รูปที่ผิด → InputValidationError
# ═══════════════════════════════════════════

@pytest.mark.parametrize("raw", [
    "",
    "   ",
    "081234567",       # 9 หลัก สั้นไป
    "08123456789",     # 11 หลัก ยาวไป
    "0212345678",      # เบอร์บ้าน กทม (หลักสอง = 2) รับ SMS ไม่ได้
    "0712345678",      # หลักสอง = 7 ไม่ใช่มือถือ
    "abcdefghij",      # ไม่ใช่ตัวเลข
    "1234567890",      # ไม่ขึ้นต้น 0
])
def test_invalid_phone_is_rejected(raw):
    with pytest.raises(InputValidationError):
        normalize_phone(raw)


def test_none_is_rejected():
    with pytest.raises(InputValidationError):
        normalize_phone(None)  # type: ignore[arg-type]


# ═══════════════════════════════════════════
# idempotent — normalize ซ้ำต้องได้เท่าเดิม
# ═══════════════════════════════════════════

def test_normalize_is_idempotent():
    """ผลของ normalize ต้องผ่าน normalize ซ้ำได้โดยไม่เปลี่ยน
    (ป้องกันบั๊กที่ค่าที่เก็บแล้วถูก normalize อีกรอบแล้วเพี้ยน)"""
    once = normalize_phone("+66812345678")
    assert normalize_phone(once) == once
