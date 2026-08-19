"""แบบ B: ส่งยอดเงิน + สูตร ให้ CRM คิดแต้มเอง (implementation ของ PointStrategy)

ทำไมแบบ B (ADR 0002): CRM คิดแต้มจากยอดเงินได้อยู่แล้ว → เราไม่ต้องเขียน Point Engine
และร้านปรับสูตรเองผ่านหน้าเว็บ CRM ได้โดยไม่ต้องรอเรา deploy

★ ชื่อไฟล์/คลาสไม่มีคำว่า loga โดยตั้งใจ (CONTEXT ข้อ 6) — ชั้นธุรกิจรู้จักแค่ "CRM"
"""
from __future__ import annotations

from app.external.crm_interface import CrmPort, PointAwardResult
from app.points.point_interface import PointStrategy
from app.receipt_data.receipt_schema import Receipt

#: ข้อความที่ "ลูกค้าจะเห็น" ในประวัติแต้มของตัวเอง — เขียนให้เข้าใจว่าแต้มมาจากไหน
_REMARK_TEMPLATE = "สะสมแต้มจากใบเสร็จ {merchant}"


class CrmFormulaStrategy(PointStrategy):
    def __init__(self, crm: CrmPort, *, formula_id: str) -> None:
        self._crm = crm
        # สูตรคิดแต้มที่ตั้งไว้ฝั่ง CRM
        # ⚠ ตอนนี้ 1 สูตรใช้ทั้งระบบ · Step 5 จะอ่านต่อร้านจากตาราง merchants แทน
        self._formula_id = formula_id

    def award(self, receipt: Receipt, *, customer_id: str, reference: str) -> PointAwardResult:
        return self._crm.add_points(
            customer_id=customer_id,
            cost=receipt.total_amount,
            formula_id=self._formula_id,
            remark=_REMARK_TEMPLATE.format(merchant=receipt.merchant),
            reference=reference,
        )
