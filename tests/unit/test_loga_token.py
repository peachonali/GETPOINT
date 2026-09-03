"""เทส app/external/loga_token.py

ใช้ httpx.MockTransport (ติดมากับ httpx อยู่แล้ว) แทน loga จริง — ไม่ต้องมี credential
ไม่ต้องต่อเน็ต และควบคุมได้ว่าให้ loga "พัง" แบบไหน ซึ่งเป็นครึ่งหนึ่งของสิ่งที่ต้องเทส
"""
import io
import logging

import httpx
import pytest

from app.external.loga_token import LogaTokenProvider, hash_password
from app.observability.logging import JsonLogFormatter
from app.reliability.errors import CrmAuthError, ExternalServiceError

BASE_URL = "https://api.loga.example"
PASSWORD = "password"
#: MD5 ของคำว่า "password" — ค่านี้คือตัวอย่างที่ loga เขียนไว้ในเอกสารเอง
#: (docs/Loga_API_Document.txt พารามิเตอร์ `pass`) ใช้เป็นหลักฐานว่าเราแฮชตรงสเปก
PASSWORD_MD5 = "5f4dcc3b5aa765d61d8327deb882cf99"


def _provider(handler, **overrides) -> LogaTokenProvider:
    """สร้าง provider ที่คุยกับ loga ปลอมตาม handler ที่ส่งเข้ามา"""
    return LogaTokenProvider(
        base_url=BASE_URL,
        user="getpoint",
        password=PASSWORD,
        device_id="4510471",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        timeout_seconds=1.0,
        **overrides,
    )


def _ok(token: str = "TOKEN-1") -> httpx.Response:
    """คำตอบ login ที่สำเร็จ — code 200 ตาม Loga API Integration Guidelines"""
    return httpx.Response(
        200,
        json={"code": 200, "msg": "success",
              "data": {"token": token, "mid": "m1", "name": "V-CLUB", "store_id": "s1"}},
    )


# ═══════════════════════════════════════════
# ทางปกติ
# ═══════════════════════════════════════════

def test_login_returns_token():
    assert _provider(lambda request: _ok()).get_token() == "TOKEN-1"


def test_token_is_cached_and_login_happens_once():
    """login ทุกครั้งที่ยิง = ยิง loga 2 เท่าโดยเปล่าประโยชน์"""
    calls = []

    def handler(request):
        calls.append(request)
        return _ok()

    provider = _provider(handler)
    provider.get_token()
    provider.get_token()
    provider.get_token()

    assert len(calls) == 1


def test_password_is_sent_as_md5_never_plaintext():
    """ถ้าหลุดเป็น plaintext = ส่งรหัสผ่านดิบข้ามเน็ต + ผิดสเปก loga ด้วย"""
    captured = {}

    def handler(request):
        captured.update(request.url.params)
        return _ok()

    _provider(handler).get_token()

    assert captured["pass"] == PASSWORD_MD5
    assert PASSWORD not in captured.values()


def test_login_sends_user_and_device_id():
    """uuid (Device ID) เป็น required ของ loga — ลืมส่ง = login ไม่ผ่านแบบงงๆ"""
    captured = {}

    def handler(request):
        captured.update(request.url.params)
        return _ok()

    _provider(handler).get_token()

    assert captured["user"] == "getpoint"
    assert captured["uuid"] == "4510471"


def test_hash_password_matches_loga_document_example():
    assert hash_password(PASSWORD) == PASSWORD_MD5


# ═══════════════════════════════════════════
# loga ปฏิเสธ (ลองใหม่ไม่ช่วย)
# ═══════════════════════════════════════════

def test_rejected_code_raises_auth_error():
    handler = lambda request: httpx.Response(200, json={"code": 401, "msg": "invalid user"})

    with pytest.raises(CrmAuthError) as exc_info:
        _provider(handler).get_token()

    assert exc_info.value.retryable is False, "รหัสผ่านผิด ลองใหม่กี่รอบก็ผิดเหมือนเดิม"
    assert exc_info.value.code == 401


def test_code_zero_is_not_treated_as_success():
    """ตรึงบั๊กที่เคยเขียนผิดจริง — เคยยึด code 0 = สำเร็จ ตามค่า placeholder ใน Swagger
    ซึ่งจะทำให้ login ที่สำเร็จจริง (code 200) ถูกมองว่าพังทุกครั้ง"""
    handler = lambda request: httpx.Response(200, json={"code": 0, "data": {"token": "X"}})

    with pytest.raises(CrmAuthError):
        _provider(handler).get_token()


def test_success_code_without_token_raises_auth_error():
    """loga บอกสำเร็จแต่ไม่มี token — ถ้าไม่ดักไว้ จะไปพังลึกๆ ตอนใช้ token = None"""
    handler = lambda request: httpx.Response(200, json={"code": 200, "msg": "ok", "data": {}})

    with pytest.raises(CrmAuthError):
        _provider(handler).get_token()


# ═══════════════════════════════════════════
# loga สะดุด (ลองใหม่อาจหาย) — ค่า retryable คือสิ่งที่ worker ใช้ตัดสินใจ
# ═══════════════════════════════════════════

def test_server_error_is_retryable():
    handler = lambda request: httpx.Response(503, text="service unavailable")

    with pytest.raises(ExternalServiceError) as exc_info:
        _provider(handler).get_token()

    assert exc_info.value.retryable is True


def test_client_error_is_not_retryable():
    """4xx = เรายิงผิดเอง (path ผิด/พารามิเตอร์ขาด) ลองใหม่ก็ผิดเหมือนเดิม"""
    handler = lambda request: httpx.Response(404, text="not found")

    with pytest.raises(ExternalServiceError) as exc_info:
        _provider(handler).get_token()

    assert exc_info.value.retryable is False


def test_timeout_is_retryable():
    def handler(request):
        raise httpx.ConnectTimeout("timed out")

    with pytest.raises(ExternalServiceError) as exc_info:
        _provider(handler).get_token()

    assert exc_info.value.retryable is True


def test_non_json_response_is_retryable():
    """เจอจริงบ่อย: proxy/หน้า maintenance ตอบ 200 มาเป็น HTML"""
    handler = lambda request: httpx.Response(200, text="<html>maintenance</html>")

    with pytest.raises(ExternalServiceError) as exc_info:
        _provider(handler).get_token()

    assert exc_info.value.retryable is True


# ═══════════════════════════════════════════
# ต่ออายุ token (loga ไม่มี refresh → ต้อง login ใหม่)
# ═══════════════════════════════════════════

def test_refresh_logs_in_again_and_replaces_token():
    tokens = iter(["TOKEN-1", "TOKEN-2"])
    handler = lambda request: _ok(next(tokens))

    provider = _provider(handler)
    first = provider.get_token()

    assert provider.refresh_token(first) == "TOKEN-2"
    assert provider.get_token() == "TOKEN-2", "ครั้งต่อไปต้องได้ตัวใหม่ ไม่ใช่ตัวที่ตายแล้ว"


def test_refresh_with_already_replaced_token_does_not_login_again():
    """กัน 'แห่ login พร้อมกัน' — งานหลายชิ้นถือ token ตัวเก่าแล้วโดนปฏิเสธพร้อมกัน
    ต้อง login แค่ครั้งเดียว ไม่ใช่ครั้งละงาน"""
    calls = []
    tokens = iter(["TOKEN-1", "TOKEN-2", "TOKEN-3"])

    def handler(request):
        calls.append(request)
        return _ok(next(tokens))

    provider = _provider(handler)
    stale = provider.get_token()          # login ครั้งที่ 1 → TOKEN-1
    provider.refresh_token(stale)         # login ครั้งที่ 2 → TOKEN-2

    assert provider.refresh_token(stale) == "TOKEN-2", "ต้องคืนตัวที่คนอื่น login มาแล้ว"
    assert len(calls) == 2, "ต้องไม่ login ครั้งที่ 3"


# ═══════════════════════════════════════════
# ความปลอดภัยของ log
# ═══════════════════════════════════════════

def test_login_never_logs_token_or_credentials():
    """loga ยัด password/token ไว้ใน query string — จุดนี้คือจุดที่หลุดง่ายที่สุดในระบบ"""
    stream = io.StringIO()
    handler_log = logging.StreamHandler(stream)
    handler_log.setFormatter(JsonLogFormatter())

    logger = logging.getLogger("app.external.loga_token")
    logger.addHandler(handler_log)
    logger.setLevel(logging.INFO)
    try:
        _provider(lambda request: _ok("SUPER-SECRET-TOKEN")).get_token()
    finally:
        logger.removeHandler(handler_log)

    written = stream.getvalue()
    assert written, "ต้องมี log บอกว่า login สำเร็จ ไม่ใช่เงียบหาย"
    assert "SUPER-SECRET-TOKEN" not in written
    assert PASSWORD_MD5 not in written
    assert "pass=" not in written
