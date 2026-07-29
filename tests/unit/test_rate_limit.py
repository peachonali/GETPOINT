"""เทส app/security/rate_limit.py — ใช้ fakeredis (ตัวนับกลางเหมือน Redis จริง)"""
import fakeredis
import pytest

from app.security.rate_limit import RateLimiter


@pytest.fixture
def redis():
    return fakeredis.FakeStrictRedis(decode_responses=True)


def _limiter(redis, *, max_hits=3, window_seconds=60) -> RateLimiter:
    return RateLimiter(redis, max_hits=max_hits, window_seconds=window_seconds)


def test_within_limit_is_allowed(redis):
    limiter = _limiter(redis, max_hits=3)
    assert all(limiter.hit("0812345678").allowed for _ in range(3))


def test_exceeding_limit_is_blocked(redis):
    limiter = _limiter(redis, max_hits=3)
    for _ in range(3):
        limiter.hit("0812345678")

    result = limiter.hit("0812345678")  # ครั้งที่ 4
    assert result.allowed is False
    assert result.retry_after_seconds > 0, "ต้องบอกลูกค้าว่ารออีกกี่วินาที"


def test_different_keys_are_counted_separately(redis):
    """คนละเบอร์/คนละคน ต้องไม่กินโควตากัน"""
    limiter = _limiter(redis, max_hits=1)
    assert limiter.hit("0811111111").allowed is True
    assert limiter.hit("0822222222").allowed is True  # คนละ key → ยังไม่เต็ม
    assert limiter.hit("0811111111").allowed is False  # key เดิม → เต็มแล้ว


def test_window_has_ttl_so_it_resets(redis):
    """ต้องตั้ง TTL ให้ counter ไม่งั้นจะจำกัดถาวร ไม่มีวันปลดล็อก"""
    limiter = _limiter(redis, max_hits=1, window_seconds=60)
    limiter.hit("0812345678")
    assert redis.ttl("ratelimit:0812345678") > 0


def test_counter_resets_after_window(redis):
    """หมดหน้าต่างเวลาแล้วต้องเริ่มนับใหม่ (จำลองด้วยการลบ key ที่ Redis จะทำเมื่อ TTL หมด)"""
    limiter = _limiter(redis, max_hits=1)
    assert limiter.hit("0812345678").allowed is True
    assert limiter.hit("0812345678").allowed is False

    redis.delete("ratelimit:0812345678")  # = หน้าต่างหมดอายุ
    assert limiter.hit("0812345678").allowed is True
