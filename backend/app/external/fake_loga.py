"""loga ปลอมในหน่วยความจำ (implementation ของ CrmPort) — ให้เทสใช้แทน loga จริง

★ หลักคิด: fake ที่ดีต้อง "บังคับกฎเดียวกับของจริง" ไม่ใช่แค่คืนค่าคงที่
    ถ้า fake ยอมให้สมัครเบอร์ซ้ำ ทั้งที่ loga จริงห้าม → เทสที่พึ่ง fake จะเขียว
    แต่พอต่อของจริงจะแดง กลายเป็น fake ที่ "โกหก" ซึ่งอันตรายกว่าไม่มี fake เลย

    fake นี้จึงจำลอง 3 กฎที่ loga บังคับจริง (ดู ADR 0003):
      1. สมัครด้วยเบอร์ที่มีอยู่แล้วไม่ได้ (ข้อ 6)
      2. reference ซ้ำ = รายการเดิม ไม่ให้แต้มซ้ำ (ข้อ 7)
      3. สมาชิกที่สมัครผ่าน endpoint บัตรพลาสติกได้ customer_id แบบ "P" + เลข

★ เป็น spy ด้วย: เก็บประวัติการเรียกไว้ให้เทสตรวจ (awards / registered)
    เทส e2e จะได้ยืนยันได้ว่า scan_job ส่ง cost/reference ที่ถูกต้องมาให้จริง
"""
from __future__ import annotations

from typing import Callable

from app.external.crm_interface import CrmCustomer, CrmPort, PointAwardResult
from app.reliability.errors import CrmCallError


def _default_point_formula(cost: float) -> int:
    """สูตรคิดแต้มปลอมสำหรับเทส — 25 บาท = 1 แต้ม

    ⚠ นี่ไม่ใช่สูตรจริงของร้านใดๆ ของจริง loga คิดจาก formula_id ที่เราไม่รู้สูตร
      มีไว้แค่ให้ยอดแต้มขยับอย่างคาดเดาได้ เทสห้ามพึ่งตัวเลขนี้ราวกับเป็นความจริงทางธุรกิจ
    """
    return int(cost // 25)


class FakeLoga(CrmPort):
    def __init__(self, point_formula: Callable[[float], int] | None = None) -> None:
        self._point_formula = point_formula or _default_point_formula

        #: สมาชิกในระบบ — key = เบอร์ (loga ระบุตัวลูกค้าด้วยเบอร์)
        self._customers: dict[str, CrmCustomer] = {}
        #: ผลการให้แต้มตาม reference — ใช้ทำ idempotency เหมือน loga
        self._awards_by_reference: dict[str, PointAwardResult] = {}
        self._next_card_number = 1

        #: ── ส่วนที่เป็น spy ให้เทสตรวจ ──
        self.awards: list[PointAwardResult] = []
        self.registered: list[CrmCustomer] = []

    # ═══════════════════════════════════════════
    # helper สำหรับจัดฉากในเทส (ไม่ใช่ส่วนของ CrmPort)
    # ═══════════════════════════════════════════

    def seed_customer(
        self, phone: str, *, name: str | None = None, customer_id: str | None = None, points: int = 0
    ) -> CrmCustomer:
        """ใส่สมาชิกที่ "มีอยู่ก่อนแล้ว" เข้าไป เพื่อเทสเส้นทางเจอสมาชิกเดิม"""
        customer = CrmCustomer(
            customer_id=customer_id or self._issue_card_id(),
            phone=phone,
            name=name,
            points_balance=points,
        )
        self._customers[phone] = customer
        return customer

    # ═══════════════════════════════════════════
    # สัญญา CrmPort
    # ═══════════════════════════════════════════

    def find_customer(self, phone: str) -> CrmCustomer | None:
        return self._customers.get(phone)

    def register_customer(self, phone: str, name: str | None = None) -> CrmCustomer:
        if phone in self._customers:
            # กฎ loga ข้อ 6 — ห้ามสมัครซ้ำด้วยเบอร์ที่มีอยู่แล้ว
            raise CrmCallError(f"เบอร์ {phone} มีสมาชิกอยู่แล้ว")

        customer = CrmCustomer(customer_id=self._issue_card_id(), phone=phone, name=name)
        self._customers[phone] = customer
        self.registered.append(customer)
        return customer

    def add_points(
        self,
        *,
        customer_id: str,
        cost: float,
        formula_id: str,
        remark: str,
        reference: str,
    ) -> PointAwardResult:
        # กฎ loga ข้อ 7 — reference ซ้ำถือเป็นรายการเดิม คืนผลเดิม ไม่ให้แต้มซ้ำ
        if reference in self._awards_by_reference:
            return self._awards_by_reference[reference]

        customer = self._find_by_customer_id(customer_id)
        if customer is None:
            raise CrmCallError(f"ไม่พบสมาชิก customer_id={customer_id}")

        earned = self._point_formula(cost)
        new_balance = (customer.points_balance or 0) + earned
        self._customers[customer.phone] = CrmCustomer(
            customer_id=customer.customer_id,
            phone=customer.phone,
            name=customer.name,
            points_balance=new_balance,
        )

        # ตรงกับของจริง: loga คืนแค่ยอดสะสมล่าสุด ไม่บอกว่ารายการนี้ได้กี่แต้ม
        result = PointAwardResult(reference=reference, points_balance=new_balance, points_added=None)
        self._awards_by_reference[reference] = result
        self.awards.append(result)
        return result

    # ═══════════════════════════════════════════
    # ภายใน
    # ═══════════════════════════════════════════

    def _issue_card_id(self) -> str:
        """ออกรหัสบัตรพลาสติกแบบ 'P' + เลข เหมือนที่ loga ทำกับสมาชิกที่ร้านสมัครให้"""
        card_id = f"P{self._next_card_number}"
        self._next_card_number += 1
        return card_id

    def _find_by_customer_id(self, customer_id: str) -> CrmCustomer | None:
        return next((c for c in self._customers.values() if c.customer_id == customer_id), None)
