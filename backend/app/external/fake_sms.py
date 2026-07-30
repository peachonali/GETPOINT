"""SMS ปลอมสำหรับเทส/dev — ไม่ส่งจริง แค่จำว่าส่งอะไรไป (impl ของ SmsPort)

ใช้ตอนเทส (ตรวจว่า member_service สั่งส่ง OTP จริง) และตอน dev (ยังไม่ต่อ vendor
ก็ทดสอบ flow ได้ โดยอ่าน OTP จาก fake.sent แทนการรอ SMS จริง)
"""
from __future__ import annotations

from app.external.sms_interface import SmsPort
from app.observability.logging import get_logger

log = get_logger(__name__)


class FakeSms(SmsPort):
    def __init__(self) -> None:
        #: ประวัติที่ "ส่ง" ไป — ให้เทสตรวจว่าส่งถูกเบอร์/ถูกรหัส
        self.sent: list[tuple[str, str]] = []

    def send_otp(self, phone: str, otp: str) -> None:
        self.sent.append((phone, otp))
        # log ผ่าน observability → เบอร์ถูก mask อัตโนมัติ (OTP ไม่ log เลย)
        log.info("FakeSms ส่ง OTP (ปลอม)", extra={"phone": phone})

    @property
    def last_otp(self) -> str | None:
        """OTP ล่าสุดที่ส่ง — สะดวกตอนเทส/dev อยากรู้รหัสไปกรอกต่อ"""
        return self.sent[-1][1] if self.sent else None
