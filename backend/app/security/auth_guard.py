"""ยามลูกค้า — ตรวจว่า request มาจาก LINE จริง แล้วบอกว่าเป็น lineUserId ไหน

★ วิธี verify: ส่ง ID token ให้ "LINE ช่วย verify" (endpoint /oauth2/v2.1/verify)
   ไม่ verify JWT เองด้วย Channel Secret เพราะ:
     1. ไม่ต้องเก็บ Channel Secret ในระบบเราเลย (ลดของลับที่ต้องดูแล)
     2. LINE ตรวจ signature/หมดอายุ/audience ให้ครบ — เราไม่ต้อง implement เอง (พลาดยาก)
   แลกกับต้องยิง network ต่อการ verify · ที่ volume เรา (auth ไม่ถี่) คุ้ม

รับ config + http client ผ่าน constructor (DI) — เทสยัด mock LINE, prod ยัด LINE จริง
"""
from __future__ import annotations

import httpx

from app.observability.logging import get_logger
from app.reliability.errors import AuthenticationError, ExternalServiceError

log = get_logger(__name__)

#: endpoint ทางการของ LINE สำหรับ verify ID token
LINE_VERIFY_URL = "https://api.line.me/oauth2/v2.1/verify"


class LineTokenVerifier:
    def __init__(
        self,
        *,
        channel_id: str,
        http_client: httpx.Client,
        verify_url: str = LINE_VERIFY_URL,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._channel_id = channel_id
        self._http = http_client
        self._verify_url = verify_url
        self._timeout = timeout_seconds

    def verify(self, id_token: str) -> str:
        """ตรวจ LIFF ID token กับ LINE แล้วคืน lineUserId (ช่อง sub)

        token ว่าง/ผิดรูป            → InputValidationError (ความผิดฝั่งผู้ใช้)
        LINE บอกว่า token ไม่ผ่าน     → CrmAuthError (ไม่ควร retry — token ใช้ไม่ได้จริง)
        LINE ติดต่อไม่ได้/ตอบแปลก     → ExternalServiceError (retry ได้)
        """
        if not id_token or not id_token.strip():
            raise AuthenticationError("ไม่พบ LINE token")

        body = self._call_line_verify(id_token)

        # ป้องกันตัวเอง: ยืนยันว่า token ออกให้ "แอปเรา" ไม่ใช่แอปอื่น
        # (LINE เช็คให้แล้วเพราะเราส่ง client_id แต่เช็คซ้ำที่นี่กันพลาด)
        if body.get("aud") != self._channel_id:
            raise AuthenticationError("LINE token ไม่ได้ออกให้แอปนี้")

        user_id = body.get("sub")
        if not user_id:
            raise ExternalServiceError("line", "LINE verify ไม่คืน userId", retryable=False)

        return user_id

    def _call_line_verify(self, id_token: str) -> dict:
        """ยิง LINE verify endpoint — แปลง error ของ LINE/httpx เป็น error ของเรา"""
        try:
            response = self._http.post(
                self._verify_url,
                data={"id_token": id_token, "client_id": self._channel_id},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise ExternalServiceError(
                "line", f"เรียก LINE verify ไม่ได้ ({type(exc).__name__})", retryable=True
            ) from exc

        # LINE ตอบ 400 เมื่อ token ผิด/หมดอายุ — เป็นความผิดของ token ไม่ใช่ระบบล่ม
        if response.status_code == httpx.codes.BAD_REQUEST:
            raise AuthenticationError("LINE token ไม่ถูกต้องหรือหมดอายุ")

        if response.status_code != httpx.codes.OK:
            raise ExternalServiceError(
                "line", f"LINE verify ตอบ HTTP {response.status_code}",
                retryable=response.status_code >= 500,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise ExternalServiceError("line", "LINE verify ตอบไม่ใช่ JSON", retryable=True) from exc
