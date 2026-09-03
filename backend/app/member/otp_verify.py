"""ตรวจ OTP — ประกอบกฎทั้งหมดเข้าด้วยกัน: ถูก + ไม่หมดอายุ + ไม่ใช้ซ้ำ + ไม่เกินครั้ง

แยกจาก otp_store เพราะคนละหน้าที่:
    otp_store  = "เก็บ/อ่าน/นับ" (คุยกับ Redis)
    otp_verify = "ตัดสินว่าผ่านไหม" (ตรรกะธุรกิจล้วน — เทสได้โดยดู outcome)

คืน OtpOutcome (enum) ไม่ใช่ bool เพราะผู้เรียก (member_service) ต้องแยกแยะเพื่อ
บอกลูกค้าให้ถูก: "รหัสผิด" / "รหัสหมดอายุ ขอใหม่" / "ลองมากไป รอสักครู่" คนละข้อความกัน
"""
from __future__ import annotations

from enum import Enum

from app.member.otp_store import OtpStore


class OtpOutcome(Enum):
    OK = "ok"                              # ถูกต้อง — ยืนยันผ่าน
    WRONG = "wrong"                        # รหัสผิด (ยังกรอกใหม่ได้)
    EXPIRED = "expired"                    # หมดอายุ/ไม่เคยขอ — ต้องขอใหม่
    TOO_MANY_ATTEMPTS = "too_many_attempts"  # กรอกผิดเกินโควตา — ถูกล็อก ขอใหม่


def verify_otp(store: OtpStore, phone: str, otp: str) -> OtpOutcome:
    """ตรวจ OTP ตามลำดับกฎที่ปลอดภัยที่สุด

    ลำดับสำคัญ: "นับครั้งก่อนเทียบรหัส" — ทุกครั้งที่กรอกถือเป็นความพยายาม 1 ครั้ง
    ไม่ว่าถูกหรือผิด จึงกัน brute force ได้จริง (ถ้านับเฉพาะตอนผิด attacker จะลองไม่จำกัด)
    """
    if not store.exists(phone):
        return OtpOutcome.EXPIRED

    attempts = store.register_attempt(phone)
    if attempts > store.max_attempts:
        store.clear(phone)  # โดนล็อกแล้ว ล้างทิ้ง บังคับให้ขอใหม่
        return OtpOutcome.TOO_MANY_ATTEMPTS

    if store.matches(phone, otp):
        store.clear(phone)  # สำเร็จ → ลบทันที กันเอา OTP เดิมมาใช้ซ้ำ
        return OtpOutcome.OK

    return OtpOutcome.WRONG
