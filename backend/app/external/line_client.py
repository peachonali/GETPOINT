"""คุยกับ LINE Messaging API — ★ Push Message แจ้งแต้มลูกค้า (impl ของ NotifierPort)

★ นี่คือปลายทางของทั้งสาย: ลูกค้าปิดแอปไปทำอย่างอื่นได้ แล้วแต้มเด้งมาเอง
  (เหตุผลทั้งหมดที่เราออกแบบเป็น async job — ADR 0002)

ใช้ Channel access token ของ Messaging API channel (คนละตัวกับ LINE Login channel
ที่ auth_guard ใช้ — ดู docs/line_setup.md)
"""
from __future__ import annotations

import httpx

from app.external.notifier_interface import NotifierPort
from app.observability.logging import get_logger, safe_url
from app.reliability.errors import ExternalServiceError

log = get_logger(__name__)

PUSH_URL = "https://api.line.me/v2/bot/message/push"

SERVICE_NAME = "line"

#: LINE จำกัดข้อความละ 5,000 ตัวอักษร — ของเราสั้นกว่ามาก แต่ตัดกันพลาดไว้
MAX_MESSAGE_LENGTH = 5000


class LineClient(NotifierPort):
    def __init__(
        self,
        *,
        channel_token: str,
        http_client: httpx.Client,
        push_url: str = PUSH_URL,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._token = channel_token
        self._http = http_client
        self._push_url = push_url
        self._timeout = timeout_seconds

    def notify(self, user_id: str, message: str) -> None:
        """ส่งข้อความหาลูกค้า 1 คน"""
        payload = {
            "to": user_id,
            "messages": [{"type": "text", "text": message[:MAX_MESSAGE_LENGTH]}],
        }

        try:
            response = self._http.post(
                self._push_url,
                json=payload,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise ExternalServiceError(
                SERVICE_NAME, f"ส่ง LINE ไม่ได้ ({type(exc).__name__})", retryable=True
            ) from exc

        if response.status_code != httpx.codes.OK:
            # 4xx = ข้อมูลเราผิด (userId ไม่ถูก/token หมดสิทธิ์) ลองใหม่ก็เหมือนเดิม
            # 5xx = ฝั่ง LINE สะดุด ลองใหม่คุ้ม
            raise ExternalServiceError(
                SERVICE_NAME,
                f"LINE push ตอบ HTTP {response.status_code}",
                retryable=response.status_code >= 500,
                code=response.status_code,
            )

        # ไม่ log ตัวข้อความ (อาจมีข้อมูลลูกค้า) และไม่ log token — log แค่ว่าส่งสำเร็จ
        log.info("ส่ง LINE push สำเร็จ", extra={"url": safe_url(self._push_url)})
