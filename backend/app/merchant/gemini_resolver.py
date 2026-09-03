"""ตัวสำรองอ่านใบเสร็จด้วย AI — ใช้ตอนกฎของเราอ่านยอดไม่ได้

★ ที่นี่คือที่ที่ 3 ชั้นความปลอดภัยมาต่อกัน (CONTEXT ข้อ 3):
    1. prompt_guard.sanitize  — ล้างข้อความก่อนเข้า AI (กัน injection)
    2. AI เดา field           — เป็น "ข้อเสนอ" ไม่ใช่ความจริง
    3. template_rules.validate — ★ ห้ามเชื่อ AI โดยไม่ผ่านกฎ
       ถ้าค่าที่ AI เดาผ่านกฎคณิตศาสตร์/ช่วงยอด/วันที่ = พอเชื่อได้
       ถ้าไม่ผ่าน = ทิ้ง ไม่ให้แต้ม (ปลอดภัยกว่าเชื่อ AI ที่อาจถูก inject)

★ ทำไมเป็น "ตัวสำรอง" ไม่ใช่ตัวหลัก:
    - กฎของเราแม่น 96% แล้ว และรันในเครื่อง ไม่มีค่าใช้จ่าย/ไม่ต้องต่อเน็ต (DEV ข้อ 5.3)
    - AI มีค่าใช้จ่ายต่อครั้ง + ช้ากว่า + เชื่อ 100% ไม่ได้
    → เรียก AI เฉพาะใบที่กฎอ่านไม่ได้จริงๆ เท่านั้น (คุ้มค่าเรียก)

★ ยังไม่ต่อเข้า scan_job อัตโนมัติ:
    ต้องมี GEMINI_API_KEY + ติดตั้ง google-genai ก่อน · เปิดใช้ผ่าน composition
    เมื่อพร้อม (ดู STATE) · ตอนนี้โครงพร้อมและเทสครบ รอแค่เปิดสวิตช์
"""
from __future__ import annotations

from dataclasses import dataclass

from app.external.ai_interface import AiExtractorPort, AiReceiptFields
from app.merchant.template_rules import validate
from app.observability.logging import get_logger
from app.security.prompt_guard import has_injection_attempt, sanitize

log = get_logger(__name__)


@dataclass(frozen=True)
class AiExtraction:
    """ผลจากตัวสำรอง AI

    trusted = ผ่านกฎตรวจแล้วหรือยัง · ผู้เรียกต้องเช็คค่านี้ก่อนใช้ total_amount
    """

    fields: AiReceiptFields
    trusted: bool
    reason: str


class GeminiResolver:
    def __init__(self, ai: AiExtractorPort) -> None:
        self._ai = ai

    def try_read(self, lines: list[str]) -> AiExtraction:
        """ลองให้ AI อ่านใบเสร็จ · คืนผลพร้อมบอกว่าเชื่อได้ไหม

        ไม่โยน error ออก — AI พังก็แค่ "อ่านไม่ได้" ระบบยังทำงานต่อได้
        (ตัวสำรองที่ล้มต้องไม่ทำให้ทั้งงานล้ม)
        """
        if has_injection_attempt(lines):
            # ไม่บล็อก แต่บันทึกไว้เฝ้าระวัง — sanitize จะจัดการตัวคำสั่งอยู่แล้ว
            log.warning("พบร่องรอย prompt injection บนใบเสร็จ — sanitize ก่อนส่ง AI")

        safe_text = sanitize(lines)

        try:
            fields = self._ai.extract_fields(safe_text)
        except Exception as exc:  # noqa: BLE001 — ตัวสำรองล้มต้องไม่ล้มทั้งงาน
            log.warning("ตัวสำรอง AI อ่านไม่สำเร็จ", extra={"detail": str(exc)})
            return AiExtraction(AiReceiptFields(), trusted=False, reason="AI อ่านไม่สำเร็จ")

        return self._judge(fields)

    def _judge(self, fields: AiReceiptFields) -> AiExtraction:
        """★ ตรวจข้อเสนอของ AI ด้วยกฎเดียวกับที่ใช้กับผลของเราเอง

        AI ไม่ได้อ่านรายการสินค้ามาให้ (คนละหน้าที่) → กฎ line_items จะ skip
        ที่ตรวจได้จริงคือ ยอดอยู่ในช่วง + วันที่ไม่ใช่อนาคต ซึ่งพอจับค่ามั่วที่ inject มาได้
        """
        if fields.total_amount is None:
            return AiExtraction(fields, trusted=False, reason="AI อ่านยอดไม่ได้")

        rules = validate(
            total_amount=fields.total_amount,
            receipt_date=fields.receipt_date,
            line_items=[],
        )
        if rules.has_hard_failure:
            log.warning(
                "ค่าที่ AI เดาไม่ผ่านกฎ — ทิ้ง",
                extra={"amount": fields.total_amount, "failed": list(rules.failed_checks)},
            )
            return AiExtraction(fields, trusted=False, reason="ค่าที่ AI เดาไม่ผ่านกฎตรวจ")

        return AiExtraction(fields, trusted=True, reason="AI อ่านได้และผ่านกฎตรวจ")
