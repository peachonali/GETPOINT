"""เทส app/member/member_service.py — orchestration ของ Step 2 ทั้งหมด

ประกอบของจริงทุกชิ้นที่เทสได้ (OtpStore+fakeredis, MemberLinker+FakeLoga, FakeSms,
RateLimiter+fakeredis, db_session) — เทสนี้จึงพิสูจน์ว่า "ชิ้นส่วนต่อกันได้จริง"
ไม่ใช่แค่แต่ละชิ้นทำงานเดี่ยวๆ
"""
import fakeredis
import pytest

from app.database.members import Member
from app.external.fake_loga import FakeLoga
from app.external.fake_sms import FakeSms
from app.member.member_link import MemberLinker
from app.member.member_service import MemberService, VerifyResult
from app.member.otp_store import OtpStore
from app.member.otp_verify import OtpOutcome
from app.security.rate_limit import RateLimiter
from app.reliability.errors import InputValidationError, RateLimitedError

TENANT = "v-club"
LINE_USER = "U-line-1"
PHONE = "0812345678"


@pytest.fixture
def sms() -> FakeSms:
    return FakeSms()


@pytest.fixture
def loga() -> FakeLoga:
    return FakeLoga()


@pytest.fixture
def service(sms, loga) -> MemberService:
    redis = fakeredis.FakeStrictRedis(decode_responses=True)
    return MemberService(
        otp_store=OtpStore(redis),
        sms=sms,
        linker=MemberLinker(loga),
        otp_rate_limiter=RateLimiter(redis, max_hits=3, window_seconds=60),
    )


# ═══════════════════════════════════════════
# request_otp
# ═══════════════════════════════════════════

def test_request_otp_sends_sms(service, sms):
    service.request_otp(PHONE)
    assert len(sms.sent) == 1
    assert sms.sent[0][0] == PHONE
    assert sms.last_otp.isdigit()


def test_request_otp_normalizes_phone(service, sms):
    """ส่งรูป +66 → SMS ต้องไปที่เบอร์รูป canonical (ไม่งั้น verify ทีหลังจะ key ไม่ตรง)"""
    service.request_otp("+66812345678")
    assert sms.sent[0][0] == PHONE


def test_request_otp_rejects_bad_phone(service):
    with pytest.raises(InputValidationError):
        service.request_otp("02-123-4567")  # เบอร์บ้าน


def test_request_otp_rate_limited(service):
    """ขอถี่เกินเพดาน → RateLimitedError (กันเผา SMS)"""
    for _ in range(3):  # max_hits = 3
        service.request_otp(PHONE)

    with pytest.raises(RateLimitedError) as exc_info:
        service.request_otp(PHONE)
    assert exc_info.value.retry_after_seconds > 0


# ═══════════════════════════════════════════
# verify_and_link — เส้นทางเต็ม
# ═══════════════════════════════════════════

def _request_then_get_otp(service, sms, phone=PHONE) -> str:
    service.request_otp(phone)
    return sms.last_otp


def test_verify_correct_otp_creates_and_links_member(service, sms, loga, db_session):
    otp = _request_then_get_otp(service, sms)

    result = service.verify_and_link(
        db_session, tenant_id=TENANT, line_user_id=LINE_USER, phone=PHONE, otp=otp
    )

    assert result.success
    assert result.member.phone == PHONE
    assert result.member.phone_verified is True
    assert result.member.crm_customer_id is not None  # ผูก loga แล้ว
    assert loga.find_customer(PHONE) is not None


def test_verify_wrong_otp_does_not_create_linked_member(service, sms, loga, db_session):
    _request_then_get_otp(service, sms)

    result = service.verify_and_link(
        db_session, tenant_id=TENANT, line_user_id=LINE_USER, phone=PHONE, otp="000000"
    )

    assert not result.success
    assert result.outcome is OtpOutcome.WRONG
    assert len(loga.registered) == 0, "OTP ผิด ห้ามแตะ loga"


def test_verify_reuses_existing_member_record(service, sms, loga, db_session):
    """คนที่แอด LINE ไว้แล้ว (มี record) มายืนยันเบอร์ → ใช้ record เดิม ไม่สร้างซ้ำ"""
    existing = Member(tenant_id=TENANT, line_user_id=LINE_USER)
    db_session.add(existing)
    db_session.commit()

    otp = _request_then_get_otp(service, sms)
    result = service.verify_and_link(
        db_session, tenant_id=TENANT, line_user_id=LINE_USER, phone=PHONE, otp=otp
    )

    assert result.member.id == existing.id
    assert db_session.query(Member).count() == 1


def test_verify_normalizes_phone(service, sms, loga, db_session):
    """ขอ OTP ด้วย 0812... แล้วยืนยันด้วย +66812... ต้องผ่าน (เบอร์เดียวกัน)"""
    otp = _request_then_get_otp(service, sms, phone=PHONE)

    result = service.verify_and_link(
        db_session, tenant_id=TENANT, line_user_id=LINE_USER, phone="+66812345678", otp=otp
    )
    assert result.success
    assert result.member.phone == PHONE


def test_expired_otp_when_never_requested(service, db_session):
    result = service.verify_and_link(
        db_session, tenant_id=TENANT, line_user_id=LINE_USER, phone=PHONE, otp="123456"
    )
    assert result.outcome is OtpOutcome.EXPIRED
