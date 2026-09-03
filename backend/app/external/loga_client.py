"""★ ที่เดียวในระบบที่คุยกับ loga (implementation ของ CrmPort)

ไฟล์นี้คือ "กำแพง" ระหว่างระบบเรากับ loga — ทุกอย่างที่เป็นเรื่องของ loga
(ชื่อ endpoint, ชื่อ field, ทางลัดแปลกๆ, การใส่ token ใน query string) หยุดอยู่ที่นี่
ข้างนอกเห็นแค่ CrmPort ที่พูดภาษาธุรกิจ

ค่าที่เหมือนกันทุกครั้ง (card_id, device_id) รับผ่าน constructor ไม่ใช่ทุกเมธอด
— ดูเหตุผลใน crm_interface.py

⚠ ไม่มีเมธอด logout โดยตั้งใจ: logout ฆ่า token ที่ทุก process ใช้อยู่ (ADR 0003 ข้อ 3)
   ระบบเราไม่มีเหตุผลต้องเรียก การไม่เขียนไว้เลยคือวิธีกันพลาดที่ถูกที่สุด
"""
from __future__ import annotations

from typing import Any

import httpx

from app.external import loga_http
from app.external.crm_interface import CrmCustomer, CrmPort, PointAwardResult
from app.external.loga_token import LogaTokenProvider
from app.observability.logging import get_logger, safe_url
from app.reliability.errors import CrmCallError

log = get_logger(__name__)

CUSTOMER_INFO_PATH = "/api/main/get_customer_info"
SUBSCRIBE_PATH = "/api/main/subscribe_by_unregistered_card"
ADD_POINT_PATH = "/api/points/add_customer_point"

#: code ที่เราเดาว่าแปลว่า "token ใช้ไม่ได้แล้ว" → login ใหม่แล้วลองอีกครั้ง
#:
#: ⚠ เป็นการเดาอย่างมีเหตุผล ไม่ใช่ของที่ยืนยันแล้ว — เอกสารทั้งสองฉบับของ loga
#:   ไม่ได้ระบุ code ของ error ไว้เลย เราเดาจากที่ loga ใช้เลขแบบ HTTP (สำเร็จ = 200)
#:   ถ้าเดาผิด: เสียแค่ login เกินมา 1 ครั้งแล้วค่อย error ตามปกติ (ไม่มีอะไรเสียหาย)
#:   ถ้าเดาถูก: ระบบกู้ตัวเองได้เมื่อมีคนเปลี่ยนรหัสผ่านผ่านเว็บ
#:   → แก้ให้ตรงทันทีที่ได้ยิงของจริง
AUTH_ERROR_CODES = frozenset({401, 403})

#: loga รับ pcard_id ผ่านช่อง cuid ได้ ถ้าใส่ "P" นำหน้า (ทางลัดที่เอกสารระบุไว้)
PLASTIC_CARD_PREFIX = "P"


def _first_present(*values: Any) -> Any | None:
    """คืนค่าตัวแรกที่มีจริง — 0 ถือว่ามีจริง มีแต่ None กับสตริงว่างที่ถือว่าไม่มี

    จำเป็นเพราะรหัสสมาชิกของ loga เป็นตัวเลข ถ้าใช้ `a or b` ตรงๆ
    สมาชิกที่มี uid = 0 จะถูกมองว่าไม่มีรหัส
    """
    for value in values:
        if value is not None and value != "":
            return value
    return None


class LogaClient(CrmPort):
    def __init__(
        self,
        *,
        base_url: str,
        card_id: str,
        device_id: str,
        token_provider: LogaTokenProvider,
        http_client: httpx.Client,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._card_id = card_id
        self._device_id = device_id
        self._tokens = token_provider
        self._http = http_client
        self._timeout = timeout_seconds

    # ═══════════════════════════════════════════
    # สัญญา CrmPort
    # ═══════════════════════════════════════════

    def find_customer(self, phone: str) -> CrmCustomer | None:
        """หาสมาชิกจากเบอร์ · ไม่เจอคืน None

        loga รับเบอร์โทรในช่อง cuid ได้ตรงๆ ไม่ต้องรู้รหัสสมาชิกมาก่อน
        """
        body = self._request(CUSTOMER_INFO_PATH, {"cuid": phone}, action="get_customer_info")

        if not loga_http.is_success(body):
            # ⚠ เอกสารไม่ได้บอกว่า code ไหนคือ "ไม่พบสมาชิก" — เราจึงถือว่าทุก code
            #   ที่ไม่สำเร็จคือไม่พบ แล้ว log code จริงไว้เพื่อให้รู้ค่าที่ถูกต้องจากของจริง
            #   ปลอดภัยพอ เพราะถ้าเป็น error จริง ขั้นถัดไป (สมัครสมาชิก) จะพังให้เห็นอยู่ดี
            log.warning(
                "get_customer_info ไม่สำเร็จ — ถือว่าไม่พบสมาชิก",
                extra={
                    "code": loga_http.code_of(body),
                    "crm_message": loga_http.message_of(body),  # ห้ามใช้ชื่อ "msg" — ชนกับ LogRecord
                },
            )
            return None

        return self._to_customer(loga_http.data_of(body), phone)

    def register_customer(self, phone: str, name: str | None = None) -> CrmCustomer:
        """สมัครสมาชิกใหม่ด้วยเบอร์โทร

        loga ออกแบบ endpoint นี้ไว้สำหรับ "บัตรพลาสติก" แต่อนุญาตให้ใช้เบอร์โทร
        แทน serial/barcode ได้เมื่อร้านไม่มีบัตรจริง ซึ่งเป็นกรณีของเรา
        ผลลัพธ์จึงเป็นสมาชิกแบบ pcard_id ไม่ใช่ uid (ดู ADR 0003 หัวข้อยังไม่ตัดสินใจ)
        """
        params = {"serial": phone, "barcode": phone, "mobile": phone}
        if name:
            params["fname"] = name

        data = self._request_ok(SUBSCRIBE_PATH, params, action="subscribe")

        pcard_id = data.get("pcard_id")
        if not _first_present(pcard_id):
            raise CrmCallError("สมัครสมาชิกผ่าน แต่ไม่ได้รหัสบัตรกลับมา")

        return CrmCustomer(
            customer_id=f"{PLASTIC_CARD_PREFIX}{pcard_id}",
            phone=phone,
            name=name,
        )

    def add_points(
        self,
        *,
        customer_id: str,
        cost: float,
        formula_id: str,
        remark: str,
        reference: str,
    ) -> PointAwardResult:
        """ให้แต้มจากยอดใช้จ่าย — ส่ง cost + formula_id ให้ loga คิดแต้มเอง (แบบ B)

        ไม่ส่ง point เด็ดขาด: ถ้าส่งไปด้วย loga จะใช้ point แล้วเก็บ cost เป็นแค่
        ข้อมูลประกอบ ซึ่งกลายเป็นวิธีแบบ A โดยไม่ตั้งใจ
        """
        params = {
            "cuid": customer_id,
            "formula_id": formula_id,
            "cost": f"{cost:.2f}",  # กันเลขทศนิยมยาวเฟื้อยแบบ 250.00000000001
            "remark": remark,
            "reference": reference,
        }

        data = self._request_ok(ADD_POINT_PATH, params, action="add_customer_point")
        balance = (data.get("point") or {}).get("now")

        log.info(
            "ให้แต้มสำเร็จ",
            extra={"reference": reference, "cost": cost, "points_balance": balance},
        )
        return PointAwardResult(
            reference=reference,
            points_balance=balance,
            points_added=None,  # loga คืนแค่ยอดสะสมล่าสุด ไม่บอกว่ารายการนี้ได้กี่แต้ม
        )

    # ═══════════════════════════════════════════
    # ภายใน
    # ═══════════════════════════════════════════

    def _request(self, path: str, params: dict[str, Any], *, action: str) -> dict:
        """ยิงคำสั่งไป loga พร้อม token · โดนปฏิเสธเรื่อง token → login ใหม่แล้วลองอีกครั้ง

        คืน body ดิบ (ยังไม่ตัดสินว่าสำเร็จหรือไม่) เพราะบางเมธอดอย่าง find_customer
        ถือว่า "ไม่สำเร็จ" เป็นคำตอบปกติ ไม่ใช่ error
        """
        token = self._tokens.get_token()
        body = self._send(path, params, token=token, action=action)

        if not loga_http.is_success(body) and loga_http.code_of(body) in AUTH_ERROR_CODES:
            log.warning(
                "CRM ปฏิเสธ token — login ใหม่แล้วลองอีกครั้ง",
                extra={"action": action, "code": loga_http.code_of(body)},
            )
            token = self._tokens.refresh_token(token)
            body = self._send(path, params, token=token, action=action)

        return body

    def _request_ok(self, path: str, params: dict[str, Any], *, action: str) -> dict:
        """เหมือน _request แต่ "ไม่สำเร็จ = error" — ใช้กับคำสั่งที่ต้องสำเร็จเท่านั้น"""
        body = self._request(path, params, action=action)

        if not loga_http.is_success(body):
            code = loga_http.code_of(body)
            raise CrmCallError(
                f"{action} ถูกปฏิเสธ (code={code}, msg={loga_http.message_of(body)!r})", code=code
            )

        return loga_http.data_of(body)

    def _send(self, path: str, params: dict[str, Any], *, token: str, action: str) -> dict:
        """เติมค่าประจำเครื่อง/ประจำร้านให้ครบ แล้วยิงจริง

        token/uuid/card_id ถูกเติมที่นี่ที่เดียว — เมธอดข้างบนจึงส่งแค่ของที่เป็น
        เรื่องของธุรกรรมนั้นๆ และไม่มีทางลืมใส่ค่าบังคับ
        """
        url = f"{self._base_url}{path}"
        full_params = {
            "token": token,
            "uuid": self._device_id,
            "card_id": self._card_id,
            **params,
        }

        log.info("เรียก CRM", extra={"action": action, "url": safe_url(url)})
        return loga_http.get_json(
            http_client=self._http,
            url=url,
            params=full_params,
            timeout_seconds=self._timeout,
            action=action,
        )

    @staticmethod
    def _to_customer(data: dict, phone: str) -> CrmCustomer | None:
        """แปลงคำตอบของ loga เป็นรูปแบบกลางของเรา

        ⚠ เอกสาร 2 ฉบับของ loga บอกตำแหน่งรหัสสมาชิกไม่ตรงกัน:
              Swagger                    → data.user_info.uid
              Integration Guidelines     → data.card.uid
          เรายังยิงของจริงไม่ได้ จึงอ่านทั้งสองที่ไปก่อน แล้วค่อยตัดทิ้งข้างที่ผิด
          เมื่อเห็นคำตอบจริง (ตัวเลือกอื่นคือเดาข้างเดียวแล้วพังแบบ "ไม่พบสมาชิก" ทุกคน)
        """
        user_info = data.get("user_info") or {}
        card = data.get("card") or {}

        uid = _first_present(user_info.get("uid"), card.get("uid"))
        pcard_id = _first_present(user_info.get("pcard_id"), card.get("pcard_id"))

        # สมาชิกออนไลน์ใช้ uid · สมาชิกบัตรพลาสติกใช้ "P" + pcard_id
        # คนที่มีทั้งคู่ (เคยเป็นบัตรพลาสติกแล้วอัปเป็นออนไลน์) ใช้ uid ได้เลย
        if uid is not None:
            customer_id = str(uid)
        elif pcard_id is not None:
            customer_id = f"{PLASTIC_CARD_PREFIX}{pcard_id}"
        else:
            log.warning("CRM ตอบว่าพบสมาชิก แต่ไม่มีรหัสสมาชิกในคำตอบ")
            return None

        name = " ".join(
            part for part in (user_info.get("fname"), user_info.get("lname")) if part
        ).strip()

        return CrmCustomer(
            customer_id=customer_id,
            phone=user_info.get("tel") or phone,
            name=name or None,
            points_balance=(data.get("point") or {}).get("now"),
        )
