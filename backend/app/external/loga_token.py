"""ขอและถือ token ของ loga — login / เก็บไว้ใช้ซ้ำ / login ใหม่เมื่อ token ตาย

แยกจาก loga_client.py เพราะเป็นคนละหน้าที่:
    ไฟล์นี้      = "ทำยังไงถึงจะได้บัตรผ่าน และบัตรหมดอายุแล้วทำยังไง"
    loga_client = "เอาบัตรผ่านไปทำธุระอะไรบ้าง"
แยกแล้วได้ผลพลอยได้: loga_client เทสได้โดยไม่ต้อง login จริง (ยัด provider ปลอมเข้าไป)

★ พฤติกรรม token ของ loga (ยืนยันแล้วจาก Loga API Integration Guidelines):
    1. token "ไม่มีวันหมดอายุ" — แต่ตายทันทีเมื่อ logout หรือมีคนเปลี่ยนรหัสผ่านผ่านเว็บ
       → ต่ออายุล่วงหน้าไม่ได้ เพราะไม่มีทางรู้ว่าใครจะไปเปลี่ยนรหัสผ่านเมื่อไหร่
         ทำได้แค่ตั้งรับ: โดนปฏิเสธเมื่อไหร่ค่อย login ใหม่ → refresh_token()
    2. ⚠⚠ ห้ามเรียก /api/main/logout เด็ดขาด — จะฆ่า token ที่ทุก process กำลังใช้อยู่
       ระบบเราไม่มีเหตุผลต้อง logout เลย จึงจงใจ "ไม่เขียน" เมธอดนั้นไว้ตั้งแต่แรก
    3. uuid ต้องเป็น string ที่คงที่ตลอดไป และต้องใช้คู่กับ token ที่ขอด้วย uuid นั้นเสมอ
    4. login สำเร็จ = code 200

⚠ ยังไม่ผูก circuit breaker (reliability/circuit_breaker.py เป็นของ Step 6)
   ตอนนี้มีแค่ timeout — จุดเสียบอยู่ที่ loga_http.get_json() ที่เดียว เพิ่มทีหลังไม่ต้องรื้อ
"""
from __future__ import annotations

import hashlib
import threading

import httpx

from app.external import loga_http
from app.observability.logging import get_logger, safe_url
from app.reliability.errors import CrmAuthError

log = get_logger(__name__)

LOGIN_PATH = "/api/main/login"


def hash_password(password: str) -> str:
    """แฮชรหัสผ่านเป็น MD5 ตามที่ loga บังคับ (พารามิเตอร์ `pass`)

    ⚠ MD5 อ่อนมาก และนี่ "ไม่ใช่ทางเลือกด้านความปลอดภัยของเรา" — เป็นข้อกำหนด
      ฝั่ง loga ที่เราแก้ไม่ได้ ห้ามใครมาเห็นบรรทัดนี้แล้วนึกว่าเราเลือกใช้ MD5 เอง
      usedforsecurity=False บอกทั้ง Python และเครื่องมือสแกนโค้ดว่าเรารู้ตัวอยู่

    สิ่งที่เราทำได้จริงคือลดความเสียหายรอบๆ: บังคับ HTTPS + ไม่ log query string
    (ดู safe_url ใน observability/logging.py)
    """
    return hashlib.md5(password.encode("utf-8"), usedforsecurity=False).hexdigest()


class LogaTokenProvider:
    """ผู้ถือ token ของ loga ประจำ process

    รับของที่ต้องใช้ผ่าน constructor ทั้งหมด (ไม่ไปอ่าน settings เอง ไม่สร้าง
    http client เอง) เพื่อให้เทสยัดของปลอมเข้ามาได้ — ตามกฎ DI ใน CONTEXT ข้อ 9.8
    ผู้ประกอบร่างคือ main.py / worker.py
    """

    def __init__(
        self,
        *,
        base_url: str,
        user: str,
        password: str,
        device_id: str,
        http_client: httpx.Client,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._user = user
        self._password_hash = hash_password(password)  # แฮชครั้งเดียว ไม่เก็บรหัสดิบไว้ใน object
        self._device_id = device_id
        self._http = http_client
        self._timeout = timeout_seconds

        self._token: str | None = None
        self._lock = threading.Lock()  # web รัน route แบบ sync ใน threadpool → มีหลายเธรดจริง

    def get_token(self) -> str:
        """คืน token ที่ใช้ได้ (ยังไม่มีก็ login ให้)"""
        token = self._token
        if token is not None:
            return token  # ทางปกติ 99% — ไม่ต้องรอ lock

        with self._lock:
            # เช็กซ้ำใน lock: ระหว่างที่เรารอคิว อาจมีเธรดอื่น login เสร็จไปแล้ว
            # ถ้าไม่เช็ก จะกลายเป็นทุกเธรดแห่ login พร้อมกันตอนระบบเพิ่งบูต
            if self._token is None:
                self._token = self._login()
            return self._token

    def refresh_token(self, stale_token: str) -> str:
        """login ใหม่ เมื่อ loga ปฏิเสธ token ที่กำลังใช้อยู่

        ต้องส่ง token ตัวที่คุณใช้แล้วโดนปฏิเสธเข้ามาด้วย เพื่อกัน "แห่ login พร้อมกัน":
        ถ้า 10 งานโดนปฏิเสธพร้อมกัน เราอยาก login แค่ครั้งเดียว ไม่ใช่ 10 ครั้ง
        (สำคัญเป็นพิเศษกับ loga เพราะยังไม่รู้ว่า login ซ้ำด้วย device id เดิม
         จะเตะ token เก่าทิ้งหรือเปล่า — ถ้าเตะ การแห่ login จะกลายเป็นเตะกันเอง)
        """
        with self._lock:
            if self._token is not None and self._token != stale_token:
                return self._token  # มีคนชิง login ใหม่ไปแล้ว ใช้ของเขาต่อได้เลย

            self._token = self._login()
            return self._token

    def _login(self) -> str:
        """แลก user/password เป็น token — ผู้เรียกต้องถือ _lock อยู่แล้ว"""
        url = f"{self._base_url}{LOGIN_PATH}"
        params = {
            "user": self._user,
            "pass": self._password_hash,
            "uuid": self._device_id,
        }

        body = loga_http.get_json(
            http_client=self._http,
            url=url,
            params=params,
            timeout_seconds=self._timeout,
            action="login",
        )

        if not loga_http.is_success(body):
            # user/password/device id ผิด — ลองใหม่กี่รอบก็ผิดเหมือนเดิม
            code = loga_http.code_of(body)
            raise CrmAuthError(
                f"login ไม่ผ่าน (code={code}, msg={loga_http.message_of(body)!r})", code=code
            )

        data = loga_http.data_of(body)
        token = data.get("token")
        if not token:
            raise CrmAuthError("login ผ่านแต่ไม่มี token กลับมา", code=loga_http.code_of(body))

        # ห้าม log ตัว token และห้าม log url เต็ม (password อยู่ใน query string)
        log.info("login loga สำเร็จ", extra={"url": safe_url(url), "store_id": data.get("store_id")})
        return token
