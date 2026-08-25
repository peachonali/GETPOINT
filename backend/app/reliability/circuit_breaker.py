"""ตัดวงจรเมื่อ external (loga) ล้มถี่ๆ — หยุดยิงชั่วคราวแทนที่จะซ้ำเติมให้ล่มหนัก

★ ทำไมต้องมี ทั้งที่มี retry แล้ว:
  retry ช่วยตอน "ล่มแวบเดียว" · แต่ตอน loga ล่มยาว (deploy พัง/ฐานข้อมูลเขาล่ม)
  การให้ทุกงานลอง retry เต็มจำนวนคือการกระหน่ำระบบที่ล้มอยู่แล้ว + ทำให้ลูกค้ารอนาน
  เปล่าๆ กว่าจะ error สุดท้าย · circuit breaker "จำ" ว่าเพิ่งล่ม แล้วตอบ error ทันที
  โดยไม่ยิงจริง จนกว่าจะถึงเวลาลองดูว่าฟื้นหรือยัง

3 สถานะ (มาตรฐาน circuit breaker):
    CLOSED    ปกติ — ยิงผ่านได้ · นับ error ต่อเนื่อง ถ้าถึงเกณฑ์ → เปิดวงจร
    OPEN      เพิ่งล่ม — ตอบ error ทันทีไม่ยิงจริง · พอครบเวลาพัก → ลองดู (HALF_OPEN)
    HALF_OPEN ทดลอง — ปล่อยผ่าน 1 ครั้ง · สำเร็จ → กลับ CLOSED · พังอีก → OPEN ต่อ

★ นับเฉพาะ error ที่ "เป็นความผิดของ external" (retryable) เท่านั้น
  4xx/ยิงผิด/รหัสผ่านผิด ไม่ใช่สัญญาณว่า loga ล่ม — ไม่ควรทำให้วงจรเปิด
  (ไม่งั้นเราส่งพารามิเตอร์ผิดครั้งเดียวแล้วบล็อกลูกค้าคนอื่นทั้งหมด)

⚠ สถานะเก็บในหน่วยความจำของ process — web กับ worker แยกวงจรกัน โดยตั้งใจ
  ที่ scale เรา (worker ตัวเดียวยิง loga) พอแล้ว · แชร์ข้ามหลาย worker ผ่าน Redis
  ค่อยทำเมื่อมี worker หลายตัวจริง (ยังไม่ใช่วันนี้ — ดู CONTEXT ข้อ 3)
"""
from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Callable, TypeVar

from app.observability.logging import get_logger
from app.reliability.errors import ExternalServiceError, GetpointError

log = get_logger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(ExternalServiceError):
    """วงจรเปิดอยู่ — ปฏิเสธทันทีโดยไม่ยิงจริง

    retryable=True เพราะ "ลองใหม่ทีหลังมีโอกาสหาย" (พอ loga ฟื้น วงจรจะปิดเอง)
    → send_queue เอาไปเข้าคิวส่งใหม่ได้ ไม่ใช่ทิ้งงาน
    """

    def __init__(self, service: str) -> None:
        super().__init__(service, "วงจรถูกตัดชั่วคราว (ปลายทางเพิ่งล้มถี่)", retryable=True)


class CircuitBreaker:
    def __init__(
        self,
        *,
        name: str = "crm",
        failure_threshold: int = 5,
        recovery_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._name = name
        self._failure_threshold = failure_threshold
        self._recovery_seconds = recovery_seconds
        self._clock = clock  # ฉีดได้เพื่อให้เทสเลื่อนเวลาเองโดยไม่ต้องรอจริง

        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = 0.0
        self._lock = threading.Lock()  # web tier ยิง route ในหลายเธรด

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._effective_state()

    def call(self, fn: Callable[[], T]) -> T:
        """ยิง fn ผ่านวงจร · วงจรเปิดอยู่ → โยน CircuitOpenError ทันที (ไม่ยิงจริง)"""
        with self._lock:
            if self._effective_state() is CircuitState.OPEN:
                raise CircuitOpenError(self._name)

        try:
            result = fn()
        except GetpointError as exc:
            # นับเฉพาะความผิดของ external จริงๆ — ยิงผิด (ไม่ retryable) ไม่ใช่ loga ล่ม
            if exc.retryable:
                self._record_failure()
            raise

        self._record_success()
        return result

    def _effective_state(self) -> CircuitState:
        """สถานะจริง ณ ตอนนี้ — เลื่อน OPEN → HALF_OPEN เองเมื่อครบเวลาพัก

        ต้องเรียกใต้ lock · ไม่แยกเป็นงานเบื้องหลัง เพราะเช็คตอนถูกเรียกก็พอ
        และไม่ต้องมีเธรดคอยปลุก (ง่ายกว่า เชื่อถือได้กว่า)
        """
        if self._state is CircuitState.OPEN:
            if self._clock() - self._opened_at >= self._recovery_seconds:
                self._state = CircuitState.HALF_OPEN
                log.info("วงจรครบเวลาพัก — ทดลองยิงดูว่าฟื้นหรือยัง", extra={"circuit": self._name})
        return self._state

    def _record_success(self) -> None:
        with self._lock:
            if self._state is not CircuitState.CLOSED:
                log.info("ปลายทางกลับมาปกติ — ปิดวงจร", extra={"circuit": self._name})
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0

    def _record_failure(self) -> None:
        with self._lock:
            # พังตอนทดลอง (HALF_OPEN) = ยังไม่ฟื้น → เปิดวงจรต่อทันที ไม่ต้องรอครบเกณฑ์
            if self._state is CircuitState.HALF_OPEN:
                self._trip()
                return

            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._trip()

    def _trip(self) -> None:
        """เปิดวงจร (ต้องเรียกใต้ lock)"""
        if self._state is not CircuitState.OPEN:
            log.warning(
                "ตัดวงจร — ปลายทางล้มถี่เกินเกณฑ์",
                extra={"circuit": self._name, "failures": self._consecutive_failures},
            )
        self._state = CircuitState.OPEN
        self._opened_at = self._clock()
