"""เทส OTP: generate + store + verify

ใช้ fakeredis (Redis in-memory) — behavior ตรง Redis จริง โดยไม่ต้องรัน Redis
decode_responses=True ให้ตรงกับ client ที่ prod จะใช้ (get คืน str)
"""
import fakeredis
import pytest

from app.member.otp_generate import OTP_LENGTH, generate_otp
from app.member.otp_store import OtpStore
from app.member.otp_verify import OtpOutcome, verify_otp

PHONE = "0812345678"


@pytest.fixture
def store() -> OtpStore:
    redis = fakeredis.FakeStrictRedis(decode_responses=True)
    return OtpStore(redis, ttl_seconds=300, max_attempts=5)


# ═══════════════════════════════════════════
# generate
# ═══════════════════════════════════════════

def test_generate_is_six_digits():
    otp = generate_otp()
    assert len(otp) == OTP_LENGTH
    assert otp.isdigit()


def test_generate_keeps_leading_zeros():
    """ถ้าเผลอคืน int แทน str เลข 0 นำหน้าจะหาย — เทส 500 ครั้งให้ชนเคสนั้น"""
    assert all(len(generate_otp()) == OTP_LENGTH for _ in range(500))


def test_generate_varies():
    """OTP ต้องไม่ซ้ำเดิมทุกครั้ง (ถ้าซ้ำ = สุ่มพัง = เดาได้)"""
    assert len({generate_otp() for _ in range(50)}) > 1


# ═══════════════════════════════════════════
# store — เก็บแบบ hash ไม่ใช่ดิบ
# ═══════════════════════════════════════════

def test_raw_otp_is_never_stored(store):
    """หัวใจความปลอดภัย — ค่าที่เก็บใน Redis ต้องไม่ใช่ OTP ดิบ"""
    store.save(PHONE, "123456")
    raw_in_redis = store._redis.get(f"otp:{PHONE}")
    assert raw_in_redis != "123456"
    assert len(raw_in_redis) == 64  # sha256 hex


def test_same_otp_different_phone_gives_different_hash(store):
    """ผูก phone กัน rainbow table — เลขเดียวกันคนละเบอร์ต้องได้ hash คนละค่า"""
    store.save("0811111111", "123456")
    store.save("0822222222", "123456")
    assert store._redis.get("otp:0811111111") != store._redis.get("otp:0822222222")


def test_save_sets_ttl(store):
    store.save(PHONE, "123456")
    assert store._redis.ttl(f"otp:{PHONE}") > 0


# ═══════════════════════════════════════════
# verify — เส้นทางหลัก
# ═══════════════════════════════════════════

def test_correct_otp_passes(store):
    store.save(PHONE, "123456")
    assert verify_otp(store, PHONE, "123456") is OtpOutcome.OK


def test_wrong_otp_fails(store):
    store.save(PHONE, "123456")
    assert verify_otp(store, PHONE, "000000") is OtpOutcome.WRONG


def test_verify_without_request_is_expired(store):
    """ไม่เคยขอ OTP (หรือหมดอายุไปแล้ว) → EXPIRED ไม่ใช่ WRONG"""
    assert verify_otp(store, PHONE, "123456") is OtpOutcome.EXPIRED


# ═══════════════════════════════════════════
# verify — กันใช้ซ้ำ + กัน brute force
# ═══════════════════════════════════════════

def test_otp_cannot_be_reused(store):
    """ยืนยันสำเร็จแล้ว OTP เดิมต้องใช้ไม่ได้อีก (ป้องกัน replay)"""
    store.save(PHONE, "123456")
    assert verify_otp(store, PHONE, "123456") is OtpOutcome.OK
    assert verify_otp(store, PHONE, "123456") is OtpOutcome.EXPIRED


def test_too_many_wrong_attempts_locks_out(store):
    """กรอกผิดครบโควตา → ล็อก แม้ครั้งถัดไปใส่ถูกก็ต้องขอใหม่ (กัน brute force)"""
    store.save(PHONE, "123456")
    for _ in range(5):  # max_attempts = 5
        assert verify_otp(store, PHONE, "000000") is OtpOutcome.WRONG

    # ครั้งที่ 6 แม้ใส่ถูกก็ถูกล็อก
    assert verify_otp(store, PHONE, "123456") is OtpOutcome.TOO_MANY_ATTEMPTS


def test_lockout_clears_otp(store):
    """หลังล็อก OTP ต้องถูกล้าง — ครั้งถัดไปเป็น EXPIRED (บังคับขอใหม่จริง)"""
    store.save(PHONE, "123456")
    for _ in range(6):
        verify_otp(store, PHONE, "000000")
    assert verify_otp(store, PHONE, "123456") is OtpOutcome.EXPIRED


def test_new_otp_resets_attempt_counter(store):
    """ขอ OTP ใหม่ = เริ่มนับใหม่ ไม่ยกโควตากรอกผิดจากรอบก่อนมา"""
    store.save(PHONE, "111111")
    for _ in range(4):
        verify_otp(store, PHONE, "000000")  # ผิด 4 ครั้ง

    store.save(PHONE, "222222")  # ขอใหม่
    assert verify_otp(store, PHONE, "222222") is OtpOutcome.OK  # ต้องไม่ติดล็อกจากรอบเก่า
