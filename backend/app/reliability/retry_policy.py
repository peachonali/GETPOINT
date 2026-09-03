"""ลองใหม่แบบ exponential backoff + jitter — สำหรับ error ที่ "ลองใหม่แล้วมีโอกาสหาย"

★ ลองใหม่เฉพาะ error ที่บอกเองว่า retryable (ดู reliability/errors.py)
  timeout / 5xx / ต่อไม่ติด → ลองใหม่คุ้ม
  รหัสผ่านผิด / 4xx / ยิงผิด → ลองกี่ครั้งก็เหมือนเดิม ต้องไม่ลองซ้ำให้เสียเวลา
  ความรู้ว่า error ไหนเป็นแบบไหนถูกเก็บไว้ตั้งแต่จุดที่เกิด — ที่นี่แค่เชื่อมัน

★ ทำไมต้องมี jitter (สุ่มบวกเข้าไป): ถ้า worker หลายตัวเจอ loga ล่มพร้อมกัน
  แล้วลองใหม่พร้อมกันเป๊ะทุกตัว จะกระหน่ำ loga เป็นระลอกตอนมันเพิ่งฟื้น (thundering herd)
  jitter กระจายเวลาลองใหม่ให้ไม่ตรงกัน

⚠ error ที่ "ไม่ retryable" หรือที่ไม่ใช่ GetpointError โยนออกทันที ไม่ลองซ้ำ
  (bug ของเราเองไม่ควรถูกลองใหม่ — มันจะพังเหมือนเดิมแล้วกลบต้นเหตุ)
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

from app.observability.logging import get_logger
from app.reliability.errors import GetpointError

log = get_logger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """กติกาการลองใหม่ — ค่าเริ่มต้นเหมาะกับการเรียก loga จาก worker

    max_attempts นับรวมครั้งแรกด้วย (3 = ยิงจริงได้มากสุด 3 ครั้ง)
    delay ครั้งที่ n = base_delay * (multiplier ** (n-1)) แล้วบวก jitter สุ่ม
        base=0.5, mult=2 → หน่วงประมาณ 0.5s, 1s ก่อนครั้งที่ 2 และ 3
    """

    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    multiplier: float = 2.0
    #: เพดานหน่วง — กันกรณี multiplier พาไปไกลเกินจน worker ค้างนาน
    max_delay_seconds: float = 8.0
    #: สุ่มบวกได้สูงสุดกี่วินาที (0 = ปิด jitter, ใช้ตอนเทสให้ผลแน่นอน)
    jitter_seconds: float = 0.3

    def __post_init__(self) -> None:
        # ตั้งค่าพังตั้งแต่ประกอบ ดีกว่าไปพังกลางการยิงจริงตอนดึกๆ
        if self.max_attempts < 1:
            raise ValueError("max_attempts ต้องอย่างน้อย 1")

    def delay_before_attempt(self, attempt: int) -> float:
        """หน่วงกี่วินาทีก่อน "ครั้งที่ attempt" (attempt เริ่มนับจาก 2 = การลองใหม่ครั้งแรก)"""
        raw = self.base_delay_seconds * (self.multiplier ** (attempt - 2))
        capped = min(raw, self.max_delay_seconds)
        return capped + random.uniform(0, self.jitter_seconds)


def with_retry(
    fn: Callable[[], T],
    *,
    policy: RetryPolicy | None = None,
    action: str = "external call",
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """เรียก fn แล้วลองใหม่ตามกติกา ถ้าเจอ error ที่ retryable

    sleep แยกออกมาเป็นพารามิเตอร์เพื่อให้เทสฉีด fake ที่ไม่หน่วงเวลาจริงได้
    (ไม่งั้นเทส retry จะช้าเป็นวินาทีต่อเคส)
    """
    policy = policy or RetryPolicy()
    last_error: GetpointError | None = None

    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn()
        except GetpointError as exc:
            if not exc.retryable:
                raise  # ลองใหม่ก็เหมือนเดิม — โยนออกทันที
            last_error = exc

            if attempt >= policy.max_attempts:
                log.warning(
                    "ลองใหม่ครบจำนวนแล้วยังไม่สำเร็จ",
                    extra={"action": action, "attempts": attempt, "detail": str(exc)},
                )
                raise

            wait = policy.delay_before_attempt(attempt + 1)
            log.info(
                "ยิงไม่สำเร็จ (ชั่วคราว) กำลังลองใหม่",
                extra={"action": action, "attempt": attempt, "wait_seconds": round(wait, 2)},
            )
            sleep(wait)

    # ไปไม่ถึงตรงนี้ตามตรรกะ แต่ใส่ไว้ให้ type checker + กันกรณีสุดวิสัย
    assert last_error is not None
    raise last_error
