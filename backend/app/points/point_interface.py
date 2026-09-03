"""สัญญา (Port) ของตัวคำนวณ/ส่งแต้ม — ทำให้แบบ A และ B สลับกันได้ (ADR 0002)

    แบบ B (ใช้ตอนนี้)  — ส่งยอดเงินให้ CRM คิดแต้มเอง  → crm_formula_strategy.py
    แบบ A (อนาคต)     — เราคิดแต้มเองแล้วส่งจำนวนแต้ม → local_engine.py (ยังไม่เขียน)

ชั้นบน (scan_job) เรียกผ่านสัญญานี้เท่านั้น จึงไม่รู้และไม่ต้องแก้เมื่อสลับวิธี
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.external.crm_interface import PointAwardResult
from app.receipt_data.receipt_schema import Receipt


class PointStrategy(ABC):
    @abstractmethod
    def award(self, receipt: Receipt, *, customer_id: str, reference: str) -> PointAwardResult:
        """ให้แต้มจากใบเสร็จ 1 ใบ

        customer_id  รหัสสมาชิกฝั่ง CRM (มาจาก members.crm_customer_id)
        reference    ลายนิ้วมือใบเสร็จ — ยิงซ้ำด้วยค่าเดิม CRM จะไม่ให้แต้มซ้ำ
        """
        raise NotImplementedError
