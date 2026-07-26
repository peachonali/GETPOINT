"""★ เทส integration ยิง loga "ของจริง" — จุดประสงค์ทั้งหมดของ Step 1

ทำไมสำคัญ: loga คือสิ่งเดียวที่เราแก้ไม่ได้ ถ้ามีเซอร์ไพรส์ต้องรู้วันนี้ ไม่ใช่เดือนหน้า
เทสด้วย fake/mock พิสูจน์ได้แค่ "โค้ดเราคุยกับสิ่งที่เราคิดว่า loga เป็น" ไม่ใช่ตัว loga จริง

★ skip อัตโนมัติเมื่อไม่มี credential — CI/เครื่องที่ไม่มี env จะไม่แดง
   วันที่ได้ credential มา แค่ใส่ .env แล้วรัน `pytest -m integration` มันจะทำงานเอง

⚠ read-only เท่านั้น: เทสนี้ยิงแค่ login + get_customer_info (ด้วยเบอร์ที่ไม่มีจริง)
   ไม่แตะ add_customer_point / subscribe เด็ดขาด เพื่อไม่ให้เกิดแต้มปลอมหรือสมาชิกปลอม
   ในระบบ loga ของลูกค้าจริง · การเทสฝั่ง write ต้องทำในบัญชี sandbox โดยตั้งใจ
"""
import os

import httpx
import pytest

from app.external.loga_client import LogaClient
from app.external.loga_token import LogaTokenProvider

pytestmark = pytest.mark.integration

#: env ที่ต้องครบถึงจะยิงของจริงได้
_REQUIRED_ENV = ("LOGA_BASE_URL", "LOGA_USER", "LOGA_PASSWORD", "LOGA_CARD_ID", "LOGA_DEVICE_ID")

#: เบอร์ที่เชื่อว่าไม่มีวันมีจริงในระบบ ใช้ทดสอบเส้นทาง "ไม่พบสมาชิก" แบบไม่แตะข้อมูลใคร
_NONEXISTENT_PHONE = "0000000000"


def _real_client() -> LogaClient | None:
    """ประกอบ client ที่ยิง loga จริงจาก env · คืน None ถ้า env ไม่ครบ"""
    missing = [key for key in _REQUIRED_ENV if not os.environ.get(key)]
    if missing:
        return None

    http = httpx.Client()
    tokens = LogaTokenProvider(
        base_url=os.environ["LOGA_BASE_URL"],
        user=os.environ["LOGA_USER"],
        password=os.environ["LOGA_PASSWORD"],
        device_id=os.environ["LOGA_DEVICE_ID"],
        http_client=http,
    )
    return LogaClient(
        base_url=os.environ["LOGA_BASE_URL"],
        card_id=os.environ["LOGA_CARD_ID"],
        device_id=os.environ["LOGA_DEVICE_ID"],
        token_provider=tokens,
        http_client=http,
    )


@pytest.fixture
def real_client() -> LogaClient:
    client = _real_client()
    if client is None:
        pytest.skip("ยังไม่มี credential ของ loga (ตั้ง LOGA_* ใน .env เพื่อเปิดเทสนี้)")
    return client


def test_query_real_loga_end_to_end(real_client: LogaClient):
    """ยิงของจริงหนึ่งครั้ง พิสูจน์ทั้งเส้นในคราวเดียว — จุดประสงค์ทั้งหมดของ Step 1

    find_customer ต้อง login (พิสูจน์ code 200 = สำเร็จ, MD5, device id ถูก) แล้ว
    ยิง get_customer_info แล้วถอด response — ครบทุกสมมติฐานที่เราเขียนลงโค้ดไว้
    ใช้เบอร์ที่ไม่มีจริง จึงคาดหวัง None และไม่แตะข้อมูลใคร

    ถ้าเอกสารสองฉบับขัดกันเรื่องตำแหน่ง uid มีผลจริง จะเห็นตรงนี้ (ดู ADR 0003)
    ผ่าน = ปลด risk ที่ Step 1 ตั้งใจปลดได้จริง · ไม่ผ่าน = ดีที่รู้ก่อนต่อทั้งระบบ

    หมายเหตุ: จงใจพิสูจน์ login ผ่าน public API (find_customer) ไม่แตะ _tokens ตรงๆ
    """
    assert real_client.find_customer(_NONEXISTENT_PHONE) is None
