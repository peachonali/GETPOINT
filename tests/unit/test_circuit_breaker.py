"""เทส app/reliability/circuit_breaker.py

ฉีด clock ปลอมเพื่อเลื่อนเวลาเองโดยไม่ต้องรอจริง
"""
import pytest

from app.reliability.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState
from app.reliability.errors import CrmCallError, ExternalServiceError


class _Clock:
    """นาฬิกาปลอม — เลื่อนเวลาได้ด้วยมือ"""
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _breaker(clock, *, threshold=3, recovery=30.0):
    return CircuitBreaker(failure_threshold=threshold, recovery_seconds=recovery, clock=clock)


def _fail():
    raise ExternalServiceError("crm", "ล่ม", retryable=True)


def test_passes_calls_when_closed():
    breaker = _breaker(_Clock())
    assert breaker.call(lambda: "ok") == "ok"
    assert breaker.state is CircuitState.CLOSED


def test_opens_after_threshold_failures():
    """★ ล้มถึงเกณฑ์ → วงจรเปิด แล้วตอบ error ทันทีโดยไม่ยิงจริง"""
    clock = _Clock()
    breaker = _breaker(clock, threshold=3)

    for _ in range(3):
        with pytest.raises(ExternalServiceError):
            breaker.call(_fail)

    assert breaker.state is CircuitState.OPEN

    # ยิงครั้งถัดไปต้องโดนปฏิเสธทันที โดยไม่เรียก fn จริง
    called = []
    with pytest.raises(CircuitOpenError):
        breaker.call(lambda: called.append(1))
    assert called == [], "วงจรเปิดต้องไม่ยิงจริง"


def test_success_resets_failure_count():
    """★ ล้มไม่ถึงเกณฑ์แล้วสำเร็จ 1 ครั้ง → นับใหม่ ไม่สะสมข้ามช่วง"""
    breaker = _breaker(_Clock(), threshold=3)

    with pytest.raises(ExternalServiceError):
        breaker.call(_fail)
    with pytest.raises(ExternalServiceError):
        breaker.call(_fail)
    breaker.call(lambda: "ok")  # สำเร็จ — รีเซ็ต

    # ล้มอีก 2 ครั้ง ยังไม่ควรเปิด (เพราะเพิ่งรีเซ็ต)
    with pytest.raises(ExternalServiceError):
        breaker.call(_fail)
    with pytest.raises(ExternalServiceError):
        breaker.call(_fail)
    assert breaker.state is CircuitState.CLOSED


def test_half_open_after_recovery_then_closes_on_success():
    """ครบเวลาพัก → ทดลองยิง 1 ครั้ง สำเร็จ → ปิดวงจรกลับปกติ"""
    clock = _Clock()
    breaker = _breaker(clock, threshold=2, recovery=30)

    for _ in range(2):
        with pytest.raises(ExternalServiceError):
            breaker.call(_fail)
    assert breaker.state is CircuitState.OPEN

    clock.advance(30)
    assert breaker.state is CircuitState.HALF_OPEN  # ครบเวลา → ทดลองได้

    breaker.call(lambda: "ok")
    assert breaker.state is CircuitState.CLOSED


def test_half_open_failure_reopens_immediately():
    """★ ทดลองยิงตอน HALF_OPEN แล้วพังอีก → เปิดวงจรทันที ไม่ต้องรอครบเกณฑ์ใหม่"""
    clock = _Clock()
    breaker = _breaker(clock, threshold=2, recovery=30)

    for _ in range(2):
        with pytest.raises(ExternalServiceError):
            breaker.call(_fail)
    clock.advance(30)
    assert breaker.state is CircuitState.HALF_OPEN

    with pytest.raises(ExternalServiceError):
        breaker.call(_fail)  # ทดลองแล้วพัง
    assert breaker.state is CircuitState.OPEN


def test_non_retryable_errors_do_not_trip():
    """★★ ยิงผิด (4xx/พารามิเตอร์ผิด) ไม่ใช่สัญญาณว่า loga ล่ม

    ถ้านับ error พวกนี้ด้วย เราส่งพารามิเตอร์ผิดครั้งเดียวจะบล็อกลูกค้าคนอื่นทั้งหมด
    """
    breaker = _breaker(_Clock(), threshold=2)

    for _ in range(5):
        with pytest.raises(CrmCallError):
            breaker.call(lambda: (_ for _ in ()).throw(CrmCallError("ยิงผิด")))

    assert breaker.state is CircuitState.CLOSED, "error ที่ไม่ใช่ความผิด external ต้องไม่เปิดวงจร"


def test_open_error_is_retryable():
    """CircuitOpenError ต้อง retryable — send_queue จะได้เอาไปเข้าคิวส่งใหม่ ไม่ทิ้งงาน"""
    assert CircuitOpenError("crm").retryable is True
