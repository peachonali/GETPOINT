"""AI ปลอมในหน่วยความจำ (implementation ของ AiExtractorPort) — ให้เทส/dev ใช้

★ บังคับกฎเดียวกับของจริง (DEV ข้อ 2.5): รับเฉพาะข้อความที่ "ผ่าน prompt_guard แล้ว"
  ของจริง (gemini_client) ก็คาดหวังแบบเดียวกัน — ถ้า fake ยอมรับข้อความดิบ
  เทสจะเขียวแบบผิดๆ แล้วไปพังตอนต่อ AI จริง
  fake ตรวจว่ามีป้าย data fence ของ prompt_guard หรือไม่ ถ้าไม่มี = ยังไม่ได้ล้าง → โยน error

★ เป็น spy: เก็บ prompt ที่ถูกส่งเข้ามาไว้ให้เทสตรวจว่า sanitize จริงก่อนส่ง
"""
from __future__ import annotations

from app.external.ai_interface import AiExtractorPort, AiReceiptFields
from app.security.prompt_guard import _DATA_FENCE


class FakeAi(AiExtractorPort):
    def __init__(self, result: AiReceiptFields | None = None) -> None:
        #: ผลที่จะคืน (ตั้งได้จากเทส) · ค่าเริ่มต้น = อ่านอะไรไม่ได้เลย
        self._result = result or AiReceiptFields()
        #: ประวัติ prompt ที่ถูกส่งเข้ามา — เทสใช้ยืนยันว่า sanitize ก่อนส่งจริง
        self.prompts: list[str] = []

    def extract_fields(self, receipt_text: str) -> AiReceiptFields:
        if _DATA_FENCE not in receipt_text:
            # ★ จำลองกฎของจริง: ต้องส่งข้อความที่ล้างแล้วเท่านั้น
            #   (ป้องกันไม่ให้มีคนเผลอส่ง OCR ดิบเข้า AI โดยข้าม prompt_guard)
            raise ValueError("ส่งข้อความที่ยังไม่ผ่าน prompt_guard เข้า AI ไม่ได้")
        self.prompts.append(receipt_text)
        return self._result
