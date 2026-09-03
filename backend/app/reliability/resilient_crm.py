"""ห่อ CrmPort ด้วย circuit breaker + retry — ทำให้การเรียก CRM ทนล่ม

★ ทำไมเป็นตัวห่อ (decorator) ไม่ใช่แก้ใน LogaClient:
  LogaClient มีหน้าที่เดียว = แปลงภาษาธุรกิจเป็น HTTP ของ loga
  "ความทนล่ม" เป็นคนละเรื่อง · แยกไว้ทำให้แต่ละไฟล์หน้าที่เดียว และวันหน้าถ้าเปลี่ยน
  CRM เป็นเจ้าอื่น ก็ห่อตัวใหม่ด้วยไฟล์นี้ได้ทันทีโดยไม่ต้องเขียน retry ซ้ำ

  ตัวห่อ implement CrmPort เหมือนกัน → ชั้นบน (point strategy) ไม่รู้เลยว่ามีการห่อ
  (Decorator pattern — สลับของจริง/ของห่อได้ที่ composition root ที่เดียว)

★ ลำดับการห่อ: circuit breaker "อยู่นอก" retry
      breaker.call( with_retry( ยิงจริง ) )
  เพื่อให้ตอน loga ล่มยาว วงจรเปิดแล้วตอบทันที โดยไม่ต้องเสีย retry เต็มจำนวนก่อน
  ส่วนตอนล่มแวบเดียว retry จัดการจบในตัวมันเอง วงจรไม่ทันเห็นเป็น failure

★ ครอบเฉพาะ "ให้แต้ม" (add_points) เท่านั้น — ไม่ครอบ find/register
  add_points คือจุดที่พลาดแล้วเสียหายจริง (ลูกค้าไม่ได้แต้ม) และเป็นงานเบื้องหลัง
  ที่ retry ได้อย่างปลอดภัย · ส่วน find/register เกิดตอนลูกค้ารออยู่หน้าจอ
  การหน่วง retry จะทำให้เขารอนาน — ให้ fail เร็วแล้วบอกให้ลองใหม่ดีกว่า
"""
from __future__ import annotations

from app.external.crm_interface import CrmCustomer, CrmPort, PointAwardResult
from app.reliability.circuit_breaker import CircuitBreaker
from app.reliability.retry_policy import RetryPolicy, with_retry


class ResilientCrm(CrmPort):
    def __init__(
        self,
        inner: CrmPort,
        *,
        breaker: CircuitBreaker | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._inner = inner
        self._breaker = breaker or CircuitBreaker(name="crm")
        self._retry = retry_policy or RetryPolicy()

    def find_customer(self, phone: str) -> CrmCustomer | None:
        # ลูกค้ารออยู่หน้าจอ — ไม่หน่วง retry แต่ยังผ่านวงจร (ถ้า loga ล่มก็ตอบเร็ว)
        return self._breaker.call(lambda: self._inner.find_customer(phone))

    def register_customer(self, phone: str, name: str | None = None) -> CrmCustomer:
        return self._breaker.call(lambda: self._inner.register_customer(phone, name))

    def add_points(
        self,
        *,
        customer_id: str,
        cost: float,
        formula_id: str,
        remark: str,
        reference: str,
    ) -> PointAwardResult:
        """งานเบื้องหลัง — ห่อทั้ง circuit breaker และ retry เต็มรูปแบบ"""
        def call() -> PointAwardResult:
            return with_retry(
                lambda: self._inner.add_points(
                    customer_id=customer_id,
                    cost=cost,
                    formula_id=formula_id,
                    remark=remark,
                    reference=reference,
                ),
                policy=self._retry,
                action="add_points",
            )

        return self._breaker.call(call)
