"""ส่ง SMS OTP ผ่านผู้ให้บริการจริง (impl ของ SmsPort)

⚠ ยังไม่ต่อ vendor จริง — send_otp ยัง raise ไว้โดยตั้งใจ (ไม่ใช่ลืม)
   ต้องเลือกผู้ให้บริการ SMS ไทยก่อน (เช่น THSMS, Twilio, ANTS) แล้วเติม HTTP call
   ตาม spec ของเจ้านั้น · dev/เทสใช้ FakeSms ไปก่อน (external/fake_sms.py)

เมื่อต่อจริง ต้องทำตาม CONTEXT:
   - อ่าน api key จาก settings เท่านั้น (มี settings.sms_api_key แล้ว)
   - มี timeout ทุก call · ผ่าน circuit breaker (Step 6)
   - ไม่ log เบอร์/OTP ดิบ (log ผ่าน observability ที่ mask ให้)
"""
from __future__ import annotations

import httpx

from app.external.sms_interface import SmsPort
from app.observability.logging import get_logger

log = get_logger(__name__)


class SmsClient(SmsPort):
    def __init__(self, *, api_key: str, base_url: str, http_client: httpx.Client) -> None:
        # รับ config + http client ผ่าน DI (ไม่อ่าน settings เอง ไม่สร้าง client เอง)
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._http = http_client

    def send_otp(self, phone: str, otp: str) -> None:
        raise NotImplementedError(
            "ยังไม่ได้ต่อผู้ให้บริการ SMS — dev/เทสใช้ FakeSms ไปก่อน (ดู docstring)"
        )
