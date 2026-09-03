"""ตัวแจ้งเตือนปลอมสำหรับเทส/dev — ไม่ส่งจริง แค่จำว่าส่งอะไรไป (impl ของ NotifierPort)"""
from __future__ import annotations

from app.external.notifier_interface import NotifierPort
from app.observability.logging import get_logger

log = get_logger(__name__)


class FakeNotifier(NotifierPort):
    def __init__(self) -> None:
        #: ประวัติที่ "ส่ง" ไป — ให้เทสตรวจว่า scan_job แจ้งลูกค้าจริงและข้อความถูกต้อง
        self.sent: list[tuple[str, str]] = []

    def notify(self, user_id: str, message: str) -> None:
        self.sent.append((user_id, message))
        log.info("FakeNotifier ส่งข้อความ (ปลอม)")

    @property
    def last_message(self) -> str | None:
        return self.sent[-1][1] if self.sent else None
