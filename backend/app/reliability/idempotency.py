"""กันทำงานซ้ำจาก "คำขอเดียวกันที่ยิงมาหลายครั้ง" — ด้วยคีย์กันซ้ำใน Redis

★ ต่างจาก duplicate_check อย่างไร:
    duplicate_check → "ใบเสร็จใบนี้เคยได้แต้มไหม" (ระดับธุรกิจ ดูจากประวัติทั้งหมด)
    idempotency    → "คำขอนี้เพิ่งยิงมาเมื่อกี้ไหม" (ระดับคำขอ ดูช่วงสั้นๆ)

  ตัวอย่าง: ลูกค้ากดปุ่มสแกนรัว 3 ที เพราะเน็ตช้า → 3 คำขอ ไฟล์เดียวกัน
  ถ้าไม่กัน จะสร้าง 3 งาน worker ทำ 3 รอบ (2 รอบหลังไปตายที่ duplicate_check
  แต่ก็เปลือง worker + ลูกค้าเห็น "กำลังทำ 3 งาน" งงๆ)
  idempotency ทำให้คำขอที่ 2-3 ได้ job_id เดิมกลับไป โดยไม่สร้างงานใหม่

★ ใช้ Redis SET NX + TTL:
    NX  = ตั้งค่าได้ต่อเมื่อยังไม่มีคีย์ → คนแรกเท่านั้นที่ "อ้างสิทธิ์" สำเร็จ
    TTL = คีย์หายเองใน N วินาที → หลังพ้นช่วงนี้ ถือเป็นการส่งใหม่ที่ตั้งใจ (ได้งานใหม่)

  ★ atomic ในคำสั่งเดียว — สำคัญมากเมื่อมีหลาย web instance:
    ถ้าเช็คก่อนแล้วค่อยตั้ง (2 คำสั่ง) สองคำขอที่มาพร้อมกันเป๊ะจะเช็คว่า "ว่าง"
    พร้อมกันทั้งคู่ แล้วสร้างงานคนละใบ · SET NX ทำเช็ค+ตั้งในจังหวะเดียว ชนกันไม่ได้

⚠ ถ้า Redis ล่ม: idempotency ใช้ไม่ได้ → ยอมให้ "อาจสร้างงานซ้ำ" ดีกว่า "รับใบเสร็จไม่ได้"
  (duplicate_check ยังเป็นตาข่ายรับสุดท้ายที่กันแต้มซ้ำอยู่) — ผู้เรียกตัดสินเรื่องนี้
"""
from __future__ import annotations

from redis import Redis

#: เก็บคีย์กันซ้ำไว้กี่วินาที — ครอบคลุม "กดรัวเพราะรอผล" แต่ไม่นานจนบล็อกการส่งใหม่ที่ตั้งใจ
#: 5 นาที = นานพอครอบเวลาที่ worker ประมวลผล 1 ใบ (7-9 วิ) + ลูกค้าลังเลกดซ้ำ
DEFAULT_TTL_SECONDS = 300


class IdempotencyStore:
    def __init__(self, redis: Redis, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    def claim(self, key: str, value: str) -> str | None:
        """อ้างสิทธิ์คีย์นี้ · เป็นคนแรก → คืน None · มีคนอ้างไว้แล้ว → คืนค่าของคนแรก

        คืน None = "เธอเป็นคนแรก ทำงานได้เลย"
        คืน str  = "คำขอนี้เพิ่งทำไปแล้ว นี่คือผลของครั้งก่อน (เช่น job_id เดิม)"
        """
        was_first = self._redis.set(self._namespaced(key), value, nx=True, ex=self._ttl)
        if was_first:
            return None
        return self._redis.get(self._namespaced(key))

    @staticmethod
    def _namespaced(key: str) -> str:
        return f"idem:{key}"
