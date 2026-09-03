"""เก็บ OTP ใน Redis — แบบ hash + หมดอายุ + นับครั้งกรอกผิด

★ เก็บ "hash" ไม่ใช่ OTP ดิบ:
    ถ้า Redis หลุด/ถูกอ่าน OTP ดิบ = ใครก็ยืนยันแทนลูกค้าได้ทันที
    เก็บ hash แล้ว attacker ได้แค่ hash ใช้ต่อไม่ได้ (เทียบตอน verify เท่านั้น)
    ผูก phone เข้าไปใน hash ด้วย → OTP เลขเดียวกันของคนละเบอร์ ได้ hash คนละค่า
    (กัน rainbow table ของเลข 6 หลักซึ่งมีแค่ล้านค่า สร้างล่วงหน้าได้)

★ รับ redis client ผ่าน constructor (DI) — เทสยัด fakeredis, prod ยัด redis จริง
   client ต้องตั้ง decode_responses=True (get คืน str ไม่ใช่ bytes)

Redis keys 2 ตัวต่อเบอร์:
    otp:{phone}          = hash ของ OTP           (หมดอายุใน ttl)
    otp:attempts:{phone} = จำนวนครั้งที่กรอก       (หมดอายุพร้อมกัน)
"""
from __future__ import annotations

import hashlib
import hmac

from redis import Redis

#: OTP มีอายุ 5 นาที — นานพอให้เปิด SMS มาพิมพ์ทัน สั้นพอไม่ให้ค้างในระบบนาน
DEFAULT_TTL_SECONDS = 300

#: กรอกผิดเกินกี่ครั้งถือว่าโดนเดา → ล็อก ต้องขอใหม่ (กัน brute force เลข 6 หลัก)
DEFAULT_MAX_ATTEMPTS = 5

_OTP_KEY = "otp:{phone}"
_ATTEMPTS_KEY = "otp:attempts:{phone}"


class OtpStore:
    def __init__(
        self,
        redis: Redis,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._redis = redis
        self._ttl = ttl_seconds
        self.max_attempts = max_attempts

    def save(self, phone: str, otp: str) -> None:
        """เก็บ OTP ใหม่ (ทับของเก่า) + รีเซ็ตตัวนับกรอกผิด

        ขอ OTP ใหม่ = เริ่มนับใหม่ ไม่ยกยอดโควตากรอกผิดจากรอบก่อนมา
        """
        self._redis.set(_OTP_KEY.format(phone=phone), self._hash(phone, otp), ex=self._ttl)
        self._redis.delete(_ATTEMPTS_KEY.format(phone=phone))

    def exists(self, phone: str) -> bool:
        """ยังมี OTP ที่ยังไม่หมดอายุค้างอยู่ไหม (ไม่มี = หมดอายุ/ไม่เคยขอ)"""
        return self._redis.exists(_OTP_KEY.format(phone=phone)) == 1

    def matches(self, phone: str, otp: str) -> bool:
        """OTP ที่กรอกตรงกับที่เก็บไหม — เทียบแบบ constant-time กัน timing attack"""
        stored = self._redis.get(_OTP_KEY.format(phone=phone))
        if stored is None:
            return False
        return hmac.compare_digest(stored, self._hash(phone, otp))

    def register_attempt(self, phone: str) -> int:
        """นับการกรอก 1 ครั้ง แล้วคืนยอดสะสม

        ตั้ง TTL ให้ตัวนับครั้งแรก เพื่อไม่ให้ counter ค้างถาวรหลัง OTP หมดอายุ
        """
        key = _ATTEMPTS_KEY.format(phone=phone)
        count = self._redis.incr(key)
        if count == 1:
            self._redis.expire(key, self._ttl)
        return count

    def clear(self, phone: str) -> None:
        """ลบ OTP + ตัวนับ — ใช้เมื่อยืนยันสำเร็จ (กันใช้ซ้ำ) หรือโดนล็อก"""
        self._redis.delete(_OTP_KEY.format(phone=phone), _ATTEMPTS_KEY.format(phone=phone))

    @staticmethod
    def _hash(phone: str, otp: str) -> str:
        """sha256 ของ phone+otp — ผูก phone กัน rainbow table ของเลข 6 หลัก"""
        return hashlib.sha256(f"{phone}:{otp}".encode("utf-8")).hexdigest()
