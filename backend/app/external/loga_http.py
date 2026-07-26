"""ชั้นล่างสุดของการคุยกับ loga — ยิง GET แล้วแปลง error ของ httpx เป็น error ของเรา

ทำไมแยกเป็นไฟล์ (ไฟล์นี้ไม่มีในพิมพ์เขียว):
    loga_token (login) กับ loga_client (ธุรกิจทุกอย่าง) ต้องจัดการ HTTP เหมือนกันเป๊ะ —
    timeout / 5xx / 4xx / ตอบมาไม่ใช่ JSON ทั้ง 4 กรณี ถ้าเขียนซ้ำสองที่ วันหนึ่งมันจะเพี้ยน
    ไปคนละทาง แล้วเราจะได้ระบบที่ "login มี retry แต่การให้แต้มไม่มี" โดยไม่มีใครตั้งใจ

    ตอนเขียน loga_token ยังมีผู้ใช้รายเดียว จึงยังไม่แยก (แยกตอนนั้น = เดาอนาคต)
    ตอนนี้มีผู้ใช้สองรายจริงแล้ว จึงแยก

ไฟล์นี้ "ไม่รู้จักธุรกิจ" — ไม่รู้ว่า login คืออะไร ไม่รู้ว่าแต้มคืออะไร
รู้แค่ว่า loga ห่อคำตอบมาในรูป {"code": ..., "msg": ..., "data": ...}
"""
from __future__ import annotations

from typing import Any

import httpx

from app.reliability.errors import ExternalServiceError

#: loga ตอบ code == 200 เมื่อสำเร็จ (ตาม Loga API Integration Guidelines)
#:
#: ⚠ อย่าหลงเชื่อ Swagger: หน้า Example Value เขียน "code": 0 ไว้ — นั่นคือค่า placeholder
#:   ที่ Swagger เติมให้ field ชนิด integer อัตโนมัติ (สังเกต field ข้างๆ เป็น "msg": "string"
#:   ซึ่งชัดว่าไม่ใช่ข้อมูลจริง) ถ้ายึด 0 ระบบจะมองว่าทุกคำสั่งที่สำเร็จคือคำสั่งที่พัง
SUCCESS_CODE = 200

#: ชื่อ service ที่ใช้ใน error/log — โดเมนรู้จักแค่คำว่า CRM ไม่ใช่ชื่อ vendor
SERVICE_NAME = "crm"


def get_json(
    *,
    http_client: httpx.Client,
    url: str,
    params: dict[str, Any],
    timeout_seconds: float,
    action: str,
) -> dict:
    """ยิง GET แล้วคืน JSON ดิบ (ยังไม่ตรวจ code)

    action = ชื่อสั้นๆ ของสิ่งที่กำลังทำ ("login", "get_customer_info") ใช้ประกอบข้อความ error
    ให้คนอ่าน log รู้ทันทีว่าพังตอนไหน โดยไม่ต้องเปิดโค้ดตาม
    """
    try:
        response = http_client.get(url, params=params, timeout=timeout_seconds)
        response.raise_for_status()
        return response.json()

    except httpx.HTTPStatusError as exc:
        # 5xx = ฝั่งเขาสะดุด ลองใหม่คุ้ม · 4xx = เรายิงผิด ลองใหม่ก็ผิดเหมือนเดิม
        status = exc.response.status_code
        raise ExternalServiceError(
            SERVICE_NAME, f"{action} ตอบ HTTP {status}", retryable=status >= 500, code=status
        ) from exc

    except httpx.HTTPError as exc:
        # timeout / ต่อไม่ติด / DNS พัง — เป็นอาการชั่วคราวโดยธรรมชาติ
        raise ExternalServiceError(
            SERVICE_NAME, f"{action} ติดต่อไม่ได้ ({type(exc).__name__})", retryable=True
        ) from exc

    except ValueError as exc:
        # ตอบ 200 แต่ไม่ใช่ JSON — เจอบ่อยเวลาโดนหน้า maintenance / proxy คั่นกลาง
        raise ExternalServiceError(
            SERVICE_NAME, f"{action} ตอบกลับไม่ใช่ JSON", retryable=True
        ) from exc


def is_success(body: dict) -> bool:
    """loga บอกว่าสำเร็จไหม (ดูจาก code ในเนื้อคำตอบ ไม่ใช่ HTTP status)"""
    return body.get("code") == SUCCESS_CODE


def code_of(body: dict) -> int | None:
    return body.get("code")


def message_of(body: dict) -> str:
    return str(body.get("msg", ""))


def data_of(body: dict) -> dict:
    """คืน data เป็น dict เสมอ

    loga ส่ง data เป็น null ได้เมื่อไม่มีข้อมูล — ถ้าไม่กันไว้ ผู้เรียกจะเจอ
    AttributeError: 'NoneType' ในจุดที่ไกลจากต้นเหตุมาก
    """
    data = body.get("data")
    return data if isinstance(data, dict) else {}
