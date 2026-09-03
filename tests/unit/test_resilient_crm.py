"""เทส app/reliability/resilient_crm.py — ตัวห่อ CrmPort ให้ทนล่ม

พิสูจน์ว่าตัวห่อทำหน้าที่ครบ: retry ตอนล่มแวบ, ตัดวงจรตอนล่มยาว,
และไม่ retry งานที่ลูกค้ารออยู่หน้าจอ (find/register)
"""
import pytest

from app.external.crm_interface import CrmCustomer, CrmPort, PointAwardResult
from app.reliability.circuit_breaker import CircuitBreaker, CircuitOpenError
from app.reliability.errors import CrmCallError, ExternalServiceError
from app.reliability.resilient_crm import ResilientCrm
from app.reliability.retry_policy import RetryPolicy


class _FakeCrm(CrmPort):
    """CRM ปลอมที่สั่งให้ล้มได้ตามต้องการ + นับจำนวนการเรียก"""
    def __init__(self):
        self.add_calls = 0
        self.find_calls = 0
        self.fail_add_times = 0     # ล้ม add_points กี่ครั้งแรก
        self.add_error = ExternalServiceError("crm", "timeout", retryable=True)

    def find_customer(self, phone):
        self.find_calls += 1
        return None

    def register_customer(self, phone, name=None):
        return CrmCustomer(customer_id="C1", phone=phone)

    def add_points(self, **kwargs):
        self.add_calls += 1
        if self.add_calls <= self.fail_add_times:
            raise self.add_error
        return PointAwardResult(reference=kwargs["reference"], points_balance=100)


def _award(crm: ResilientCrm):
    return crm.add_points(customer_id="C1", cost=100.0, formula_id="7", remark="x", reference="r1")


#: retry ที่ไม่หน่วงจริง (jitter=0, base เล็ก) — เทสต้องเร็ว
_FAST_RETRY = RetryPolicy(max_attempts=3, base_delay_seconds=0, jitter_seconds=0)


def test_add_points_retries_transient_failure():
    """★ loga ล่มแวบเดียว (2 ครั้งแรก) → retry จนสำเร็จ ลูกค้าได้แต้ม"""
    inner = _FakeCrm()
    inner.fail_add_times = 2
    crm = ResilientCrm(inner, retry_policy=_FAST_RETRY)

    result = _award(crm)
    assert result.points_balance == 100
    assert inner.add_calls == 3


def test_add_points_gives_up_after_retries():
    """ล่มตลอด → เลิกลองตามจำนวน แล้วโยน error (ให้ scan_job ทำเครื่องหมาย FAILED)"""
    inner = _FakeCrm()
    inner.fail_add_times = 99
    crm = ResilientCrm(inner, retry_policy=_FAST_RETRY)

    with pytest.raises(ExternalServiceError):
        _award(crm)
    assert inner.add_calls == 3


def test_non_retryable_error_not_retried():
    """★ ยิงผิด (พารามิเตอร์ผิด) → ไม่ retry ยิงครั้งเดียวพอ"""
    inner = _FakeCrm()
    inner.fail_add_times = 99
    inner.add_error = CrmCallError("พารามิเตอร์ผิด")  # retryable=False
    crm = ResilientCrm(inner, retry_policy=_FAST_RETRY)

    with pytest.raises(CrmCallError):
        _award(crm)
    assert inner.add_calls == 1


def test_circuit_opens_after_repeated_failure():
    """★ loga ล่มยาว → วงจรเปิด แล้วตอบทันทีโดยไม่ยิง loga อีก

    ป้องกันการกระหน่ำ loga ที่ล้มอยู่ + ไม่ทำให้ลูกค้าถัดๆ ไปรอ retry เต็มจำนวนเปล่าๆ
    """
    inner = _FakeCrm()
    inner.fail_add_times = 999
    breaker = CircuitBreaker(failure_threshold=2)
    crm = ResilientCrm(inner, breaker=breaker, retry_policy=_FAST_RETRY)

    # 2 งานแรก retry เต็มที่แล้วล้ม → วงจรเปิด
    for _ in range(2):
        with pytest.raises(ExternalServiceError):
            _award(crm)
    calls_before = inner.add_calls

    # งานถัดไปต้องโดนปฏิเสธทันที โดยไม่แตะ loga อีกเลย
    with pytest.raises(CircuitOpenError):
        _award(crm)
    assert inner.add_calls == calls_before, "วงจรเปิดแล้วต้องไม่ยิง loga อีก"


def test_find_customer_is_not_retried():
    """★ find เกิดตอนลูกค้ารออยู่หน้าจอ — ห้ามหน่วง retry ให้เขารอนาน"""
    inner = _FakeCrm()
    crm = ResilientCrm(inner, retry_policy=_FAST_RETRY)

    crm.find_customer("0812345678")
    assert inner.find_calls == 1
