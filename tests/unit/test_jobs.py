"""เทส app/jobs/ — JobQueue + JobStatusStore (ใช้ fakeredis)"""
import fakeredis
import pytest

from app.jobs.job_queue import JobQueue, ScanJob
from app.jobs.job_status import JobState, JobStatusStore

JOB = ScanJob(
    job_id="job-1", tenant_id="v-club", member_id=7,
    receipt_id="rcp-1", image_key="receipts/v-club/rcp-1.jpg",
)


@pytest.fixture
def redis():
    return fakeredis.FakeStrictRedis(decode_responses=True)


# ═══════════════════════════════════════════
# JobQueue
# ═══════════════════════════════════════════

def test_enqueue_then_dequeue_roundtrip(redis):
    queue = JobQueue(redis)
    queue.enqueue(JOB)

    assert queue.dequeue(block_seconds=1) == JOB


def test_dequeue_returns_none_when_empty(redis):
    """คิวว่างเป็นเรื่องปกติของ worker — ต้องคืน None ไม่ใช่ error"""
    assert JobQueue(redis).dequeue(block_seconds=1) is None


def test_queue_is_fifo(redis):
    """งานที่เข้าก่อนต้องได้ทำก่อน — ลูกค้าที่ส่งก่อนไม่ควรรอนานกว่า"""
    queue = JobQueue(redis)
    first = ScanJob("job-1", "v-club", 1, "r1", "k1")
    second = ScanJob("job-2", "v-club", 2, "r2", "k2")

    queue.enqueue(first)
    queue.enqueue(second)

    assert queue.dequeue(block_seconds=1).job_id == "job-1"
    assert queue.dequeue(block_seconds=1).job_id == "job-2"


def test_job_taken_by_only_one_worker(redis):
    """งานหนึ่งใบต้องถูกหยิบได้ครั้งเดียว — ไม่งั้นแต้มจะถูกให้ซ้ำ"""
    queue = JobQueue(redis)
    queue.enqueue(JOB)

    assert queue.dequeue(block_seconds=1) is not None
    assert queue.dequeue(block_seconds=1) is None, "หยิบซ้ำต้องไม่ได้งานเดิม"


def test_pending_count(redis):
    queue = JobQueue(redis)
    assert queue.pending_count() == 0
    queue.enqueue(JOB)
    queue.enqueue(JOB)
    assert queue.pending_count() == 2


def test_corrupt_payload_is_skipped_not_crashing(redis):
    """ข้อมูลเสียในคิวต้องไม่ทำ worker ตายทั้งตัว"""
    redis.rpush("queue:scan", "{ไม่ใช่ json}")
    assert JobQueue(redis).dequeue(block_seconds=1) is None


def test_job_survives_serialization_with_thai(redis):
    thai_job = ScanJob("job-ไทย", "v-club", 1, "ใบเสร็จ-1", "receipts/ก.jpg")
    queue = JobQueue(redis)
    queue.enqueue(thai_job)
    assert queue.dequeue(block_seconds=1) == thai_job


# ═══════════════════════════════════════════
# JobStatusStore
# ═══════════════════════════════════════════

def test_mark_then_get(redis):
    store = JobStatusStore(redis)
    store.mark("job-1", JobState.QUEUED)

    status = store.get("job-1")
    assert status.state is JobState.QUEUED
    assert status.job_id == "job-1"


def test_status_transitions(redis):
    """เดินครบเส้น: queued → processing → succeeded"""
    store = JobStatusStore(redis)
    store.mark("job-1", JobState.QUEUED)
    store.mark("job-1", JobState.PROCESSING)
    store.mark("job-1", JobState.SUCCEEDED, points_balance=125)

    status = store.get("job-1")
    assert status.state is JobState.SUCCEEDED
    assert status.points_balance == 125


def test_failed_status_carries_customer_message(redis):
    store = JobStatusStore(redis)
    store.mark("job-1", JobState.FAILED, message="รูปเบลอเกินไป กรุณาถ่ายใหม่")

    status = store.get("job-1")
    assert status.state is JobState.FAILED
    assert "เบลอ" in status.message


def test_unknown_job_returns_none(redis):
    assert JobStatusStore(redis).get("ไม่มีงานนี้") is None


def test_status_has_ttl(redis):
    """สถานะเป็นข้อมูลชั่วคราว ต้องหมดอายุเอง ไม่ให้ Redis บวม"""
    JobStatusStore(redis).mark("job-1", JobState.QUEUED)
    assert redis.ttl("job:job-1") > 0
