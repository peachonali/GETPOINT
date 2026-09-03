"""เทส app/reliability/idempotency.py — คีย์กันซ้ำระดับคำขอ"""
import fakeredis
import pytest

from app.reliability.idempotency import IdempotencyStore


@pytest.fixture
def redis():
    return fakeredis.FakeStrictRedis(decode_responses=True)


def test_first_claim_returns_none(redis):
    """คนแรก → None (ทำงานได้)"""
    store = IdempotencyStore(redis)
    assert store.claim("scan:abc", "job-1") is None


def test_second_claim_returns_first_value(redis):
    """★ คนที่สองด้วยคีย์เดิม → ได้ค่าของคนแรกกลับ (job เดิม) ไม่ใช่ None"""
    store = IdempotencyStore(redis)
    store.claim("scan:abc", "job-1")

    assert store.claim("scan:abc", "job-2") == "job-1"


def test_different_keys_independent(redis):
    """คนละคีย์ = คนละคำขอ ต้องไม่บล็อกกัน"""
    store = IdempotencyStore(redis)
    assert store.claim("scan:abc", "job-1") is None
    assert store.claim("scan:xyz", "job-2") is None


def test_expires_after_ttl(redis):
    """★ พ้น TTL → คีย์หาย ถือเป็นการส่งใหม่ที่ตั้งใจ (ได้งานใหม่)"""
    store = IdempotencyStore(redis, ttl_seconds=100)
    store.claim("scan:abc", "job-1")

    redis.delete("idem:scan:abc")  # จำลองว่า TTL หมด

    assert store.claim("scan:abc", "job-2") is None


def test_ttl_is_set(redis):
    """ต้องตั้ง TTL จริง — ไม่งั้นคีย์ค้างตลอดกาล บล็อกการส่งใหม่ถาวร"""
    IdempotencyStore(redis, ttl_seconds=300).claim("scan:abc", "job-1")
    assert redis.ttl("idem:scan:abc") > 0
