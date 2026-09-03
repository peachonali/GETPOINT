"""สุ่มรหัส OTP

★ ใช้ secrets ไม่ใช่ random:
    random เป็น pseudo-random ที่คาดเดาได้ถ้ารู้ seed → OTP ถูกเดาได้
    secrets เป็น cryptographically secure — ออกแบบมาสำหรับ token/รหัสผ่านโดยเฉพาะ
    OTP คือด่านยืนยันตัวตน เดาได้ = ยืมตัวตนคนอื่นได้
"""
from __future__ import annotations

import secrets

#: OTP 6 หลัก — สมดุลระหว่างจำง่าย (พิมพ์ใน 5 นาที) กับเดายาก (1 ใน 1,000,000)
OTP_LENGTH = 6


def generate_otp() -> str:
    """สุ่ม OTP เป็นสตริงตัวเลข OTP_LENGTH หลัก (เติม 0 นำหน้า)

    คืน str ไม่ใช่ int เพราะ "012345" ต้องคงเลข 0 นำหน้าไว้ (int จะกลายเป็น 12345)
    """
    upper_bound = 10**OTP_LENGTH
    return f"{secrets.randbelow(upper_bound):0{OTP_LENGTH}d}"
