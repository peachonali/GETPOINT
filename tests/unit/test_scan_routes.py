"""เทส /scan และ /jobs/{id} — ประตู HTTP ของการสแกน

พิสูจน์พฤติกรรมที่ ADR 0002 สัญญาไว้: ตอบ 202 ทันทีโดยไม่ประมวลผล
(งานต้องไปโผล่ในคิวให้ worker ทำต่อ ไม่ใช่ทำเสร็จใน request)
"""
import io

import fakeredis
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.database.db import get_session
from app.database.members import Member
from app.jobs.job_queue import JobQueue
from app.jobs.job_status import JobState, JobStatusStore
from app.main import app
from app.reliability.idempotency import IdempotencyStore
from app.routes.dependencies import (
    get_idempotency_store,
    get_image_store,
    get_job_queue,
    get_job_status,
    get_line_verifier,
    get_scan_rate_limiter,
    get_tenant_id,
)
from app.security.rate_limit import RateLimiter
from app.storage.image_store import ImageStore
from app.storage.local_storage import LocalStorage

TENANT = "v-club"
LINE_USER = "U-line-1"
HEADER = {"Authorization": "Bearer good-token"}


class _StubVerifier:
    def verify(self, token: str) -> str:
        return LINE_USER


def _photo(size=(800, 1200)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(250, 250, 250)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _upload(photo: bytes | None = None):
    return {"image": ("receipt.jpg", photo or _photo(), "image/jpeg")}


@pytest.fixture
def ctx(db_session, tmp_path):
    redis = fakeredis.FakeStrictRedis(decode_responses=True)
    queue = JobQueue(redis)
    status_store = JobStatusStore(redis)
    images = ImageStore(LocalStorage(tmp_path / "storage"))

    member = Member(
        tenant_id=TENANT, line_user_id=LINE_USER, phone="0812345678",
        phone_verified=True, crm_customer_id="P1",
    )
    db_session.add(member)
    db_session.commit()

    app.dependency_overrides[get_line_verifier] = lambda: _StubVerifier()
    app.dependency_overrides[get_tenant_id] = lambda: TENANT
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_image_store] = lambda: images
    app.dependency_overrides[get_job_queue] = lambda: queue
    app.dependency_overrides[get_job_status] = lambda: status_store
    app.dependency_overrides[get_scan_rate_limiter] = lambda: RateLimiter(
        redis, max_hits=20, window_seconds=600
    )
    app.dependency_overrides[get_idempotency_store] = lambda: IdempotencyStore(redis)

    yield {
        "client": TestClient(app), "queue": queue, "status": status_store,
        "images": images, "member": member, "session": db_session,
    }

    app.dependency_overrides.clear()


# ═══════════════════════════════════════════
# ★ POST /scan — ต้องตอบ 202 ทันที ไม่ประมวลผล
# ═══════════════════════════════════════════

def test_submit_returns_202_with_job_id(ctx):
    resp = ctx["client"].post("/scan", files=_upload(), headers=HEADER)

    assert resp.status_code == 202
    body = resp.json()
    assert body["job_id"]
    assert body["state"] == JobState.QUEUED.value


def test_submit_puts_job_in_queue_not_processed(ctx):
    """★ หัวใจของ async: request จบแล้วงานยังอยู่ในคิว รอ worker มาทำ"""
    ctx["client"].post("/scan", files=_upload(), headers=HEADER)

    assert ctx["queue"].pending_count() == 1
    job = ctx["queue"].dequeue(block_seconds=1)
    assert job.member_id == ctx["member"].id
    assert job.tenant_id == TENANT


def test_submit_stores_the_image(ctx):
    resp = ctx["client"].post("/scan", files=_upload(), headers=HEADER)
    job = ctx["queue"].dequeue(block_seconds=1)

    stored = ctx["images"].get(TENANT, job.receipt_id)
    assert stored.startswith(b"\xff\xd8\xff"), "ต้องเก็บเป็น JPEG ที่ผ่าน upload_check แล้ว"
    assert resp.headers["Location"] == f"/jobs/{job.job_id}"


def test_double_submit_same_image_returns_same_job(ctx):
    """★ กดรัวไฟล์เดิม → job เดิม + คิวมีงานเดียว (ไม่สร้างงานซ้ำ)"""
    photo = _photo()
    first = ctx["client"].post("/scan", files=_upload(photo), headers=HEADER)
    second = ctx["client"].post("/scan", files=_upload(photo), headers=HEADER)

    assert first.json()["job_id"] == second.json()["job_id"]
    assert ctx["queue"].pending_count() == 1, "ต้องมีงานเดียวในคิว ไม่ใช่สองงาน"


def test_status_is_queued_right_after_submit(ctx):
    job_id = ctx["client"].post("/scan", files=_upload(), headers=HEADER).json()["job_id"]
    assert ctx["status"].get(job_id).state is JobState.QUEUED


# ═══════════════════════════════════════════
# การกั้นก่อนเข้าคิว
# ═══════════════════════════════════════════

def test_unverified_member_is_rejected(ctx):
    """ยังไม่ยืนยันเบอร์ = ส่งใบเสร็จไม่ได้ · ต้องกั้นที่ประตู ไม่ปล่อยไปพังที่ worker"""
    ctx["member"].phone_verified = False
    ctx["member"].crm_customer_id = None
    ctx["session"].commit()

    resp = ctx["client"].post("/scan", files=_upload(), headers=HEADER)

    assert resp.status_code == 400
    assert ctx["queue"].pending_count() == 0, "ไม่ผ่านการกั้น ต้องไม่เข้าคิว"


def test_without_line_token_is_401(ctx):
    resp = ctx["client"].post("/scan", files=_upload())
    assert resp.status_code == 401
    assert ctx["queue"].pending_count() == 0


def test_non_image_upload_is_rejected(ctx):
    resp = ctx["client"].post(
        "/scan", files={"image": ("evil.jpg", b"#!/bin/sh\nrm -rf /", "image/jpeg")},
        headers=HEADER,
    )
    assert resp.status_code == 400
    assert ctx["queue"].pending_count() == 0


def test_rate_limited_after_too_many_uploads(ctx):
    # ★ สร้าง limiter ครั้งเดียวนอก lambda — ถ้าสร้างในนั้นจะได้ตัวนับใหม่ทุก request
    #   (ตัวนับรีเซ็ตตลอด แล้วเทสจะเขียวแบบผิดๆ)
    limiter = RateLimiter(
        fakeredis.FakeStrictRedis(decode_responses=True), max_hits=2, window_seconds=600
    )
    app.dependency_overrides[get_scan_rate_limiter] = lambda: limiter
    client = ctx["client"]
    for _ in range(2):
        client.post("/scan", files=_upload(), headers=HEADER)

    resp = client.post("/scan", files=_upload(), headers=HEADER)
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


# ═══════════════════════════════════════════
# GET /jobs/{id}
# ═══════════════════════════════════════════

def test_read_job_status(ctx):
    job_id = ctx["client"].post("/scan", files=_upload(), headers=HEADER).json()["job_id"]

    resp = ctx["client"].get(f"/jobs/{job_id}", headers=HEADER)

    assert resp.status_code == 200
    assert resp.json()["state"] == JobState.QUEUED.value


def test_read_job_reflects_success(ctx):
    """หลัง worker ทำเสร็จ หน้าจอที่ถามอยู่ต้องเห็นผลลัพธ์"""
    job_id = ctx["client"].post("/scan", files=_upload(), headers=HEADER).json()["job_id"]
    ctx["status"].mark(job_id, JobState.SUCCEEDED, points_balance=125)

    body = ctx["client"].get(f"/jobs/{job_id}", headers=HEADER).json()
    assert body["state"] == "succeeded"
    assert body["points_balance"] == 125


def test_unknown_job_returns_400(ctx):
    resp = ctx["client"].get("/jobs/ไม่มีงานนี้", headers=HEADER)
    assert resp.status_code == 400


def test_job_status_requires_line_token(ctx):
    assert ctx["client"].get("/jobs/whatever").status_code == 401
