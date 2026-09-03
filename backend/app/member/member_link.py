"""★ ผูก member เข้ากับ loga — ที่ที่ lineUserId ↔ phone ↔ crm_customer_id มาบรรจบ

หัวใจของ Step 2: หลังยืนยันเบอร์ด้วย OTP แล้ว ต้องรู้ว่าเบอร์นี้คือสมาชิก loga คนไหน
(หรือสมัครใหม่ให้) แล้วจำ crm_customer_id ไว้ เพื่อส่งแต้มเข้าถูกคนตอนสแกนใบเสร็จ

รับ CrmPort ผ่าน constructor (DI) — เทสยัด fake_loga, prod ยัด LogaClient
โดเมนไม่รู้จักชื่อ loga รู้แค่ว่ามี CRM (ตาม CONTEXT ข้อ 6)
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.database.members import Member
from app.external.crm_interface import CrmCustomer, CrmPort
from app.observability.logging import get_logger, log_context
from app.reliability.errors import CrmCallError, InputValidationError

log = get_logger(__name__)


class MemberLinker:
    def __init__(self, crm: CrmPort) -> None:
        self._crm = crm

    def link(self, session: Session, member: Member) -> Member:
        """ผูก member (ที่ยืนยันเบอร์แล้ว) เข้ากับ CRM แล้วเก็บ crm_customer_id

        ★ idempotent — เรียกซ้ำปลอดภัย: ถ้าผูกไว้แล้วคืนเลย ไม่ยิง CRM ซ้ำ
          จำเป็นเพราะ verify OTP กับ link เป็นคนละ commit (ดู member_service):
          ถ้า CRM ล่มหลัง verify สำเร็จ เบอร์ถูกยืนยันไปแล้ว ลูกค้าไม่ต้อง OTP ใหม่
          แค่ retry link ได้เลย — เมธอดนี้จึงต้องทนถูกเรียกซ้ำ
        """
        if not member.phone:
            # ไม่ควรเกิด (member_service เช็คก่อนแล้ว) แต่กันพลาดเชิงโครงสร้าง
            raise InputValidationError("ต้องยืนยันเบอร์ก่อนผูกสมาชิกกับ CRM")

        if member.crm_customer_id:
            return member  # ผูกไว้แล้ว ไม่ทำซ้ำ

        customer = self._resolve_crm_customer(member.phone)
        member.crm_customer_id = customer.customer_id
        session.commit()

        with log_context(tenant_id=member.tenant_id):
            log.info("ผูกสมาชิกกับ CRM สำเร็จ", extra={"crm_customer_id": customer.customer_id})
        return member

    def _resolve_crm_customer(self, phone: str) -> CrmCustomer:
        """หาสมาชิกใน CRM · ไม่มีก็สมัคร · ชนเบอร์ซ้ำก็เอาตัวที่มีอยู่

        ADR 0003 #6: loga ห้ามสมัครซ้ำด้วยเบอร์ที่มีอยู่ → ต้อง find ก่อน register เสมอ
        แต่ระหว่าง find (ไม่เจอ) กับ register อาจมีอีก request สมัครเบอร์เดียวกันไปก่อน
        (คนกดสองเครื่อง / retry ซ้อน) → register จะโดนปฏิเสธ
        → จับไว้แล้ว find อีกรอบ เอาตัวที่เพิ่งถูกสร้าง แทนที่จะพังทั้งการสมัคร
        """
        existing = self._crm.find_customer(phone)
        if existing is not None:
            return existing

        try:
            return self._crm.register_customer(phone)
        except CrmCallError:
            # ปฏิเสธเพราะเบอร์ซ้ำ (race) เป็นเคสที่กู้ได้ · เหตุอื่นกู้ไม่ได้
            recovered = self._crm.find_customer(phone)
            if recovered is None:
                raise  # ไม่ใช่เบอร์ซ้ำจริง — register พังด้วยเหตุอื่น โยนต่อให้ชั้นบนเห็น
            return recovered
