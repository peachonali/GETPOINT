"""เทส app/routes/auth_routes.py + main.py (HTTP layer + composition)

ใช้ FastAPI TestClient + override dependencies ให้ชี้ของปลอม — เทสนี้พิสูจน์
"เส้นทาง HTTP ต่อกันจริง" (route → member_service → db → loga) + error → HTTP status ถูก
"""
import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.database.db import get_session
from app.external.fake_loga import FakeLoga
from app.external.fake_sms import FakeSms
from app.main import app
from app.member.member_link import MemberLinker
from app.member.member_service import MemberService
from app.member.otp_store import OtpStore
from app.reliability.errors import AuthenticationError
from app.routes.dependencies import (
    get_line_verifier,
    get_member_service,
    get_tenant_id,
)
from app.security.rate_limit import RateLimiter

PHONE = "0812345678"
GOOD_HEADER = {"Authorization": "Bearer good-line-token"}


class _StubVerifier:
    """แทน LINE — คืน lineUserId คงที่ หรือโยน error ตามที่ตั้ง"""

    def __init__(self, user_id="U-test-user", error=None):
        self._user_id = user_id
        self._error = error

    def verify(self, token: str) -> str:
        if self._error:
            raise self._error
        return self._user_id


@pytest.fixture
def ctx(db_session):
    """ประกอบ service ของปลอมทั้งชุด + override deps ของ app แล้วคืน client"""
    redis = fakeredis.FakeStrictRedis(decode_responses=True)
    fake_sms = FakeSms()
    fake_loga = FakeLoga()
    service = MemberService(
        otp_store=OtpStore(redis),
        sms=fake_sms,
        linker=MemberLinker(fake_loga),
        otp_rate_limiter=RateLimiter(redis, max_hits=5, window_seconds=600),
    )

    app.dependency_overrides[get_member_service] = lambda: service
    app.dependency_overrides[get_line_verifier] = lambda: _StubVerifier()
    app.dependency_overrides[get_tenant_id] = lambda: "v-club"
    app.dependency_overrides[get_session] = lambda: db_session

    yield {"client": TestClient(app), "sms": fake_sms, "loga": fake_loga}

    app.dependency_overrides.clear()


# ═══════════════════════════════════════════
# /auth/request-otp
# ═══════════════════════════════════════════

def test_request_otp_ok(ctx):
    resp = ctx["client"].post("/auth/request-otp", json={"phone": PHONE}, headers=GOOD_HEADER)
    assert resp.status_code == 200
    assert resp.json()["status"] == "otp_sent"
    assert len(ctx["sms"].sent) == 1


def test_request_otp_without_token_is_401(ctx):
    """ไม่แนบ Authorization → ยืนยันตัวตนไม่ผ่าน (ไม่ใช่ 500)"""
    resp = ctx["client"].post("/auth/request-otp", json={"phone": PHONE})
    assert resp.status_code == 401
    assert ctx["sms"].sent == [], "ไม่ผ่านยาม ต้องไม่ยิง SMS"


def test_request_otp_bad_phone_is_400(ctx):
    resp = ctx["client"].post(
        "/auth/request-otp", json={"phone": "02-123-4567"}, headers=GOOD_HEADER
    )
    assert resp.status_code == 400


def test_request_otp_rate_limited_is_429(ctx):
    client = ctx["client"]
    for _ in range(5):  # max_hits = 5
        client.post("/auth/request-otp", json={"phone": PHONE}, headers=GOOD_HEADER)

    resp = client.post("/auth/request-otp", json={"phone": PHONE}, headers=GOOD_HEADER)
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers  # บอก client รออีกกี่วินาที


def test_invalid_line_token_is_401(ctx):
    """token มีแต่ LINE ปฏิเสธ → 401 (ต่างจาก loga ล่มที่เป็น 502)"""
    app.dependency_overrides[get_line_verifier] = lambda: _StubVerifier(
        error=AuthenticationError("token ปลอม")
    )
    resp = ctx["client"].post("/auth/request-otp", json={"phone": PHONE}, headers=GOOD_HEADER)
    assert resp.status_code == 401


# ═══════════════════════════════════════════
# /auth/verify
# ═══════════════════════════════════════════

def _request_otp(ctx) -> str:
    ctx["client"].post("/auth/request-otp", json={"phone": PHONE}, headers=GOOD_HEADER)
    return ctx["sms"].last_otp


def test_verify_ok_creates_and_links_member(ctx):
    otp = _request_otp(ctx)

    resp = ctx["client"].post(
        "/auth/verify", json={"phone": PHONE, "otp": otp}, headers=GOOD_HEADER
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "verified"
    assert body["crm_customer_id"] is not None
    assert ctx["loga"].find_customer(PHONE) is not None  # ผูก loga แล้วจริง


def test_verify_wrong_otp_is_400(ctx):
    _request_otp(ctx)
    resp = ctx["client"].post(
        "/auth/verify", json={"phone": PHONE, "otp": "000000"}, headers=GOOD_HEADER
    )
    assert resp.status_code == 400
    assert "OTP" in resp.json()["error"]


def test_verify_without_token_is_401(ctx):
    resp = ctx["client"].post("/auth/verify", json={"phone": PHONE, "otp": "123456"})
    assert resp.status_code == 401
