"""ตระกูล error ของทั้งระบบ — ประกาศรวมศูนย์ที่เดียว

ทำไมต้องรวมศูนย์ (แทนที่จะให้แต่ละไฟล์ประกาศ exception ของตัวเอง):
    1. routes แปลง error เป็น HTTP response รูปแบบเดียวกันได้ที่เดียว — ชั้นบนไม่ต้อง
       รู้จัก exception ของ httpx/redis/vendor ทุกตัว
    2. worker ตัดสินใจได้ว่า error ไหน "ลองใหม่แล้วหาย" (→ retry) กับ error ไหน
       "ลองกี่ครั้งก็เหมือนเดิม" (→ dead letter) โดยดู .retryable ไม่ต้องเดาจากข้อความ
    3. เห็นภาพรวมว่าระบบเราพังได้กี่แบบ ในไฟล์เดียว

ตอนนี้มีเท่าที่ใช้จริง ไฟล์นี้จะโตตาม Step (LINE/SMS/Gemini/OCR ยังไม่ถึงคิว)
ส่วนตัวแปลง error → HTTP response จะมาตอนเขียน exception handler ใน main.py
(ยังไม่เขียนวันนี้เพราะยังไม่มี route ไหนเรียกใช้ = จะกลายเป็น dead code)
"""
from __future__ import annotations


class GetpointError(Exception):
    """แม่ของ error ทุกตัวที่ระบบเราตั้งใจโยน

    จับตัวนี้ตัวเดียว = จับเหตุการณ์ที่เรา "คาดไว้แล้ว" ทั้งหมด
    ส่วน error ที่ไม่ได้สืบจากคลาสนี้ = bug ของเรา ไม่ใช่เหตุการณ์ที่ออกแบบรับไว้
    """

    #: ลองใหม่แล้วมีโอกาสหายไหม — retry_policy / send_queue ใช้ค่านี้ตัดสินใจ
    retryable: bool = False


class InputValidationError(GetpointError):
    """ข้อมูลจากผู้ใช้ไม่ผ่านการตรวจ (เบอร์ผิดรูป / OTP ผิดรูป / ไฟล์อัปโหลดผิด)

    ตั้งชื่อไม่ทับ pydantic.ValidationError โดยเจตนา เพื่อไม่ให้สับสนตอน import
    retryable=False — ส่งข้อมูลเดิมซ้ำกี่ครั้งก็ผิดเหมือนเดิม ต้องให้ผู้ใช้แก้ก่อน
    routes จะจับตัวนี้แปลงเป็น HTTP 400 (คนละชั้นกับ error ของระบบภายนอก)
    """

    retryable = False


class DuplicateReceiptError(GetpointError):
    """ใบเสร็จใบนี้เคยถูกใช้รับแต้มไปแล้ว (ดู receipt_check/duplicate_check.py)

    ★ ไม่ใช่ "ระบบพัง" และไม่ใช่ "ลูกค้าทำผิด" — เป็นผลลัพธ์เชิงธุรกิจที่ตั้งใจให้เกิด
      จึงแยกออกจาก InputValidationError เพื่อให้ log/สถิติแยกสองเรื่องนี้ออกจากกันได้
      (ใบซ้ำเยอะ = พฤติกรรมลูกค้า · อ่านไม่ออกเยอะ = คุณภาพ OCR — คนละปัญหากันคนละวิธีแก้)

    retryable=False — ส่งรูปเดิมใหม่กี่ครั้งก็ซ้ำเหมือนเดิม
    """

    retryable = False

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        #: เหตุผลเชิงเทคนิคว่าตัดสินจากอะไร — ใส่ log/หน้าแอดมิน ไม่ใช่ข้อความหาลูกค้า
        self.reason = reason


class AuthenticationError(GetpointError):
    """ผู้เรียกไม่ได้ยืนยันตัวตน / token ไม่ถูกต้อง (LINE token หาย / ผิด / หมดอายุ)

    แยกจาก CrmAuthError (ซึ่งเป็นเรื่อง credential ของ "เรา" ต่อ loga = ปัญหาฝั่ง server)
    ตัวนี้คือ "ผู้เรียกยังไม่ได้ล็อกอิน" = ปัญหาฝั่ง client → routes แปลงเป็น HTTP 401
    """

    retryable = False


class RateLimitedError(GetpointError):
    """ผู้ใช้ทำถี่เกินเพดานที่กำหนด (ขอ OTP รัว, กด /scan รัว)

    retryable=True แต่ "ต้องรอ" — ต่างจาก error อื่นที่ retry ได้ทันที
    routes จะจับตัวนี้แปลงเป็น HTTP 429 พร้อมบอก retry_after_seconds ให้ลูกค้า
    """

    retryable = True

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"ทำรายการถี่เกินไป กรุณารออีก {retry_after_seconds} วินาที")
        self.retry_after_seconds = retry_after_seconds


class ExternalServiceError(GetpointError):
    """ระบบภายนอกตอบผิดพลาด (CRM / LINE / SMS / Gemini)

    retryable ถูกกำหนด ณ จุดที่เกิดเหตุ เพราะที่นั่นคือที่เดียวที่รู้ว่าพังเพราะอะไร
    (timeout → ลองใหม่คุ้ม · รหัสผ่านผิด → ลองอีกกี่รอบก็ผิดเหมือนเดิม)
    ถ้าไม่เก็บตั้งแต่ตอนเกิด ชั้นบนจะต้องเดาเอาจากข้อความ error ซึ่งเปราะมาก
    """

    def __init__(
        self,
        service: str,
        message: str,
        *,
        retryable: bool = True,
        code: int | None = None,
    ) -> None:
        super().__init__(f"[{service}] {message}")
        self.service = service
        self.code = code          # รหัสที่ปลายทางส่งมา (loga ใช้ field ชื่อ code)
        self.retryable = retryable


class CrmAuthError(ExternalServiceError):
    """CRM ปฏิเสธเพราะ credential/token ใช้ไม่ได้

    แยกเป็นคลาสของตัวเองเพราะวิธีแก้ต่างจาก error อื่นโดยสิ้นเชิง:
    retry เฉยๆ ไม่ช่วย — ต้อง login ใหม่ก่อนแล้วค่อยลองใหม่ (ดู loga_client)
    """

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__("crm", message, retryable=False, code=code)


class CrmCallError(ExternalServiceError):
    """CRM รับคำสั่งแล้ว "ปฏิเสธเชิงธุรกิจ" (ตอบ code ที่ไม่ใช่สำเร็จ)

    เช่น สมัครด้วยเบอร์ที่มีอยู่แล้ว / cuid ไม่มีในระบบ / พารามิเตอร์ไม่ครบ
    ต่างจาก ExternalServiceError ทั่วไปตรงที่ "ระบบเขาปกติดี แต่เขาไม่ยอมทำให้"
    → ยิงใหม่กี่รอบก็ได้คำตอบเดิม (retryable=False) ต้องแก้ที่ข้อมูลที่เราส่งไป
    """

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__("crm", message, retryable=False, code=code)
