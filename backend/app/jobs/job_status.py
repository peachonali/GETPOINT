"""สถานะงานสแกน — ให้ลูกค้าถามได้ว่า "ใบที่เพิ่งส่งไป ถึงไหนแล้ว"

หน้าจอ ProcessingScreen จะถาม GET /jobs/{id} เป็นระยะ จนกว่าจะเสร็จ
(LINE Push เป็นช่องทางหลักในการแจ้งผล ตัวนี้เป็นช่องทางเสริมสำหรับคนที่ยังเปิดหน้าค้างอยู่)

★ เก็บใน Redis พร้อม TTL ไม่ใช่ Postgres:
    สถานะเป็นข้อมูลชั่วคราว (มีค่าแค่ไม่กี่นาทีระหว่างรอผล) — ไม่ควรไปบวมตารางถาวร
    ส่วน "ผลลัพธ์ถาวร" (ใบเสร็จ/แต้มที่ได้) เก็บในตาราง receipts ต่างหาก
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum

from redis import Redis

_KEY = "job:{job_id}"

#: เก็บสถานะไว้ 1 ชั่วโมง — นานพอให้ลูกค้าเปิดดูย้อนหลังได้ สั้นพอไม่ให้ Redis บวม
DEFAULT_TTL_SECONDS = 3600


class JobState(str, Enum):
    """สถานะของงาน — ใช้ str enum เพื่อให้แปลงเป็น JSON ได้ตรงๆ

    QUEUED → PROCESSING → SUCCEEDED / FAILED  (ไปข้างหน้าทางเดียว ไม่ย้อนกลับ)
    """

    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class JobStatus:
    job_id: str
    state: JobState
    #: ข้อความบอกลูกค้าเมื่อล้มเหลว (เช่น "รูปเบลอเกินไป") — ห้ามใส่รายละเอียดภายในระบบ
    message: str | None = None
    #: แต้มที่ได้รับ (มีเมื่อสำเร็จ)
    points_balance: int | None = None

    def to_json(self) -> str:
        data = asdict(self)
        data["state"] = self.state.value
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "JobStatus":
        data = json.loads(raw)
        data["state"] = JobState(data["state"])
        return cls(**data)


class JobStatusStore:
    def __init__(self, redis: Redis, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    def set(self, status: JobStatus) -> None:
        """บันทึกสถานะ (ทับของเดิม) พร้อมต่ออายุ TTL"""
        self._redis.set(_KEY.format(job_id=status.job_id), status.to_json(), ex=self._ttl)

    def mark(
        self,
        job_id: str,
        state: JobState,
        *,
        message: str | None = None,
        points_balance: int | None = None,
    ) -> JobStatus:
        """ทางลัดที่ใช้บ่อยที่สุด — เปลี่ยนสถานะแล้วคืนค่าที่บันทึก"""
        status = JobStatus(
            job_id=job_id, state=state, message=message, points_balance=points_balance
        )
        self.set(status)
        return status

    def get(self, job_id: str) -> JobStatus | None:
        """อ่านสถานะ · ไม่พบ (หมดอายุ/ไม่เคยมี) → None"""
        raw = self._redis.get(_KEY.format(job_id=job_id))
        return JobStatus.from_json(raw) if raw else None
