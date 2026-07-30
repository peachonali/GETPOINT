"""เทส app/security/auth_guard.py — LineTokenVerifier

ใช้ httpx.MockTransport เลียนแบบ LINE verify endpoint — ไม่ต้องต่อ LINE จริง
และควบคุมได้ว่าให้ LINE "ตอบแบบไหน" ซึ่งเป็นครึ่งหนึ่งของสิ่งที่ต้องเทส
"""
import httpx
import pytest

from app.security.auth_guard import LINE_VERIFY_URL, LineTokenVerifier
from app.reliability.errors import AuthenticationError, ExternalServiceError

CHANNEL_ID = "1234567890"
LINE_USER_ID = "U0123456789abcdef"


def _verifier(handler) -> LineTokenVerifier:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return LineTokenVerifier(channel_id=CHANNEL_ID, http_client=http)


def _line_ok(*, aud=CHANNEL_ID, sub=LINE_USER_ID) -> httpx.Response:
    """คำตอบ verify ที่ผ่านของ LINE (มี aud + sub)"""
    return httpx.Response(200, json={"iss": "https://access.line.me", "sub": sub, "aud": aud})


# ═══════════════════════════════════════════
# สำเร็จ
# ═══════════════════════════════════════════

def test_valid_token_returns_line_user_id():
    assert _verifier(lambda r: _line_ok()).verify("good-token") == LINE_USER_ID


def test_sends_token_and_channel_id_to_line():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(httpx.QueryParams(request.content.decode())))
        return _line_ok()

    _verifier(handler).verify("the-token")
    assert captured["id_token"] == "the-token"
    assert captured["client_id"] == CHANNEL_ID  # LINE ใช้ตัวนี้ verify audience


# ═══════════════════════════════════════════
# token ไม่ผ่าน (ไม่ควร retry)
# ═══════════════════════════════════════════

def test_empty_token_is_rejected_without_calling_line():
    called = False

    def handler(request):
        nonlocal called
        called = True
        return _line_ok()

    with pytest.raises(AuthenticationError):
        _verifier(handler).verify("")
    assert called is False, "token ว่างต้องไม่เปลือง network call ไป LINE"


def test_line_400_means_bad_token():
    handler = lambda r: httpx.Response(400, json={"error": "invalid_request"})
    with pytest.raises(AuthenticationError):
        _verifier(handler).verify("expired-token")


def test_token_for_another_app_is_rejected():
    """token ที่ aud เป็นแอปอื่น — ต้องไม่ยอมรับ (กันเอา token แอปอื่นมาสวมรอย)"""
    with pytest.raises(AuthenticationError):
        _verifier(lambda r: _line_ok(aud="9999999999")).verify("other-app-token")


def test_missing_sub_is_error():
    with pytest.raises(ExternalServiceError):
        _verifier(lambda r: _line_ok(sub=None)).verify("weird-token")


# ═══════════════════════════════════════════
# LINE ล่ม/สะดุด (retry ได้)
# ═══════════════════════════════════════════

def test_line_unreachable_is_retryable():
    def handler(request):
        raise httpx.ConnectTimeout("timeout")

    with pytest.raises(ExternalServiceError) as exc_info:
        _verifier(handler).verify("token")
    assert exc_info.value.retryable is True


def test_line_500_is_retryable():
    with pytest.raises(ExternalServiceError) as exc_info:
        _verifier(lambda r: httpx.Response(503)).verify("token")
    assert exc_info.value.retryable is True


def test_verify_url_is_line_official():
    """กันแก้ endpoint หลุดไปโดเมนอื่นโดยไม่ตั้งใจ (จะส่ง token ให้ปลายทางผิด)"""
    assert LINE_VERIFY_URL == "https://api.line.me/oauth2/v2.1/verify"
