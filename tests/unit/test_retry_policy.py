"""เทส app/reliability/retry_policy.py

★ สองด้านที่ตรงข้ามกัน:
    retryable   → ต้องลองใหม่จนสำเร็จหรือครบจำนวน
    ไม่ retryable → ต้องโยนออกทันที ไม่เสียเวลาลองซ้ำ (ยิงผิดลองกี่รอบก็ผิด)
"""
import pytest

from app.reliability.errors import CrmCallError, ExternalServiceError, InputValidationError
from app.reliability.retry_policy import RetryPolicy, with_retry

#: sleep ปลอมที่ไม่หน่วงจริง + จำว่าถูกเรียกกี่ครั้ง (เทสต้องไม่ช้าเป็นวินาที)
class _FakeSleep:
    def __init__(self):
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def _retryable(msg="timeout"):
    return ExternalServiceError("crm", msg, retryable=True)


def test_succeeds_first_try_no_sleep():
    sleep = _FakeSleep()
    result = with_retry(lambda: "ok", sleep=sleep)
    assert result == "ok"
    assert sleep.calls == []


def test_retries_then_succeeds():
    """ล้ม 2 ครั้งแรก สำเร็จครั้งที่ 3 → ต้องคืนผล และ sleep 2 ครั้ง"""
    sleep = _FakeSleep()
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise _retryable()
        return "ok"

    result = with_retry(flaky, sleep=sleep)
    assert result == "ok"
    assert len(attempts) == 3
    assert len(sleep.calls) == 2


def test_gives_up_after_max_attempts():
    """★ ล้มทุกครั้ง → ยิงจริงเท่ากับ max_attempts พอดี แล้วโยน error สุดท้าย"""
    sleep = _FakeSleep()
    attempts = []

    def always_fail():
        attempts.append(1)
        raise _retryable("ยังล่ม")

    policy = RetryPolicy(max_attempts=3, jitter_seconds=0)
    with pytest.raises(ExternalServiceError, match="ยังล่ม"):
        with_retry(always_fail, policy=policy, sleep=sleep)

    assert len(attempts) == 3, "ต้องยิงจริง 3 ครั้ง ไม่ขาดไม่เกิน"
    assert len(sleep.calls) == 2, "หน่วงระหว่างครั้ง = attempts - 1"


def test_non_retryable_raises_immediately():
    """★ error ที่ลองใหม่ก็เหมือนเดิม (4xx/ยิงผิด) ต้องไม่ลองซ้ำเลย"""
    sleep = _FakeSleep()
    attempts = []

    def bad_request():
        attempts.append(1)
        raise CrmCallError("พารามิเตอร์ผิด")  # retryable=False

    with pytest.raises(CrmCallError):
        with_retry(bad_request, sleep=sleep)

    assert len(attempts) == 1, "ยิงครั้งเดียว ห้ามลองซ้ำ"
    assert sleep.calls == []


def test_input_validation_error_is_not_retried():
    """InputValidationError (retryable=False) ก็ต้องไม่ลองซ้ำ"""
    attempts = []

    def fn():
        attempts.append(1)
        raise InputValidationError("รูปเบลอ")

    with pytest.raises(InputValidationError):
        with_retry(fn, sleep=_FakeSleep())
    assert len(attempts) == 1


def test_backoff_grows_exponentially():
    """หน่วงต้องเพิ่มแบบทวีคูณ (ไม่นับ jitter)"""
    policy = RetryPolicy(base_delay_seconds=0.5, multiplier=2.0, jitter_seconds=0)
    assert policy.delay_before_attempt(2) == 0.5   # ก่อนลองครั้งที่ 2
    assert policy.delay_before_attempt(3) == 1.0
    assert policy.delay_before_attempt(4) == 2.0


def test_backoff_is_capped():
    """หน่วงต้องไม่พุ่งเกินเพดาน แม้ทวีคูณจะพาไปไกล"""
    policy = RetryPolicy(base_delay_seconds=1, multiplier=10, max_delay_seconds=5, jitter_seconds=0)
    assert policy.delay_before_attempt(5) == 5.0


def test_invalid_policy_rejected_at_construction():
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)
