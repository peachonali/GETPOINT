"""จำกัดจำนวนครั้งต่อคนต่อช่วงเวลา — ใช้ Redis (ไม่ใช่ memory)

★ ทำไม Redis ไม่ใช่ตัวแปรในหน่วยความจำ:
    พอมี web instance ตัวที่ 2 (ซึ่งต้องมีเพื่อ availability) ตัวนับใน memory จะแยกกัน
    → คนกดสลับไปโดน instance อื่นก็นับใหม่ = จำกัดไม่ได้จริง (CONTEXT ข้อ 2/3)
    Redis เป็นที่นับกลางที่ทุก instance เห็นตรงกัน

ใช้ที่ไหน (คนละ key คนละเพดาน):
    ขอ OTP    — กันสแปม SMS (แต่ละ SMS มีค่าเงิน)
    ยิง /scan — กันกดรัวถล่ม worker
    login admin — กันเดารหัส

★ fixed-window counter: นับต่อหน้าต่างเวลาตายตัว (เช่น 5 ครั้ง/นาที)
   ยอมรับ burst ที่ขอบหน้าต่างได้สูงสุด ~2 เท่า — ที่ < 2 RPS ไม่เป็นปัญหา
   (sliding window แม่นกว่าแต่ซับซ้อนกว่ามาก ยังไม่คุ้ม — ดู blueprint ส่วนที่ 3)
"""
from __future__ import annotations

from dataclasses import dataclass

from redis import Redis

_KEY = "ratelimit:{name}"


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    #: ถ้าโดนจำกัด บอกว่าต้องรออีกกี่วินาทีถึงลองใหม่ได้ (ให้ route ส่งกลับลูกค้า)
    retry_after_seconds: int = 0


class RateLimiter:
    """ตัวนับกลางบน Redis — 1 instance ต่อ 1 นโยบาย (เพดาน + หน้าต่างเวลา)

    รับ redis client ผ่าน constructor (DI) — เทสยัด fakeredis, prod ยัด redis จริง
    """

    def __init__(self, redis: Redis, *, max_hits: int, window_seconds: int) -> None:
        self._redis = redis
        self._max_hits = max_hits
        self._window = window_seconds

    def hit(self, name: str) -> RateLimitResult:
        """นับ 1 ครั้งสำหรับ key นี้ แล้วบอกว่าผ่านหรือโดนจำกัด

        name = ตัวระบุผู้ถูกนับ เช่น "otp_request:0812345678" หรือ "scan:U-lineid"
        เรียกครั้งนี้ = ใช้โควตา 1 หน่วยเสมอ (นับก่อนตัดสิน) — ผู้เรียกต้องเรียกเมื่อ
        ตั้งใจจะทำจริงเท่านั้น
        """
        key = _KEY.format(name=name)
        count = self._redis.incr(key)

        # ครั้งแรกของหน้าต่าง: เริ่มจับเวลา · เผื่อ process ตายหลัง incr ก่อน expire
        # ครั้งถัดไปที่ยังไม่มี TTL ก็ตั้งให้ (กัน key ค้างถาวร)
        if count == 1 or self._redis.ttl(key) < 0:
            self._redis.expire(key, self._window)

        if count > self._max_hits:
            retry_after = self._redis.ttl(key)
            return RateLimitResult(allowed=False, retry_after_seconds=max(retry_after, 0))

        return RateLimitResult(allowed=True)
