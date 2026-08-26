"""ประตู HTTP รับรูปใบเสร็จ — ★ ตอบ 202 ทันที ไม่รอประมวลผล (ADR 0002)

    รับรูป → ตรวจไฟล์ → เก็บรูป → โยนเข้าคิว → ตอบ 202 + job_id   (เป้า < 500ms)

งานหนักทั้งหมด (OCR/CRM) เป็นหน้าที่ worker — route นี้ห้ามทำอะไรที่ช้า
เพราะทุกวินาทีที่ค้างคือลูกค้านั่งมองหน้าจอหมุน
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.db import get_session
from app.database.members import Member
from app.jobs.job_queue import JobQueue, ScanJob
from app.jobs.job_status import JobState, JobStatusStore
from app.observability.logging import get_logger, log_context
from app.receipt_data.receipt_identity import image_fingerprint
from app.reliability.errors import InputValidationError, RateLimitedError
from app.routes.auth_routes import require_line_user
from app.routes.dependencies import (
    get_idempotency_store,
    get_image_store,
    get_job_queue,
    get_job_status,
    get_scan_rate_limiter,
    get_tenant_id,
)
from app.reliability.idempotency import IdempotencyStore
from app.security.rate_limit import RateLimiter
from app.security.upload_check import MAX_UPLOAD_BYTES, check_and_clean_image
from app.storage.image_store import ImageStore

log = get_logger(__name__)

router = APIRouter(prefix="/scan", tags=["scan"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def submit_scan(
    response: Response,
    image: UploadFile = File(...),
    line_user_id: str = Depends(require_line_user),
    tenant_id: str = Depends(get_tenant_id),
    session: Session = Depends(get_session),
    images: ImageStore = Depends(get_image_store),
    queue: JobQueue = Depends(get_job_queue),
    status_store: JobStatusStore = Depends(get_job_status),
    limiter: RateLimiter = Depends(get_scan_rate_limiter),
    idempotency: IdempotencyStore = Depends(get_idempotency_store),
) -> dict:
    """รับรูปใบเสร็จ 1 ใบเข้าคิว · ตอบ 202 พร้อม job_id ให้เอาไปถามสถานะต่อ"""
    with log_context(tenant_id=tenant_id):
        limit = limiter.hit(f"scan:{line_user_id}")
        if not limit.allowed:
            raise RateLimitedError(limit.retry_after_seconds)

        member = _require_verified_member(session, tenant_id, line_user_id)
        cleaned = check_and_clean_image(_read_upload(image))

        # receipt_id มาจากลายนิ้วมือของไฟล์ → ส่งไฟล์เดิมซ้ำจะทับ key เดิม ไม่เปลืองที่เก็บ
        receipt_id = image_fingerprint(tenant_id, cleaned)

        # ★ กดรัวไฟล์เดิมใน 5 นาที → คืน job เดิม ไม่สร้างงานซ้ำ (ดู idempotency.py)
        #   ผูกคีย์กับ "คน + ไฟล์" เพื่อไม่ให้คนละคนที่ส่งไฟล์เหมือนกันมาบล็อกกัน
        new_job_id = uuid.uuid4().hex
        claimed = idempotency.claim(f"scan:{tenant_id}:{line_user_id}:{receipt_id}", new_job_id)
        if claimed is not None:
            log.info("คำขอสแกนซ้ำ — คืน job เดิม", extra={"job_id": claimed})
            response.headers["Location"] = f"/jobs/{claimed}"
            return {"job_id": claimed, "state": JobState.QUEUED.value}

        image_key = images.put(tenant_id, receipt_id, cleaned)
        job = ScanJob(
            job_id=new_job_id,
            tenant_id=tenant_id,
            member_id=member.id,
            receipt_id=receipt_id,
            image_key=image_key,
        )
        status_store.mark(job.job_id, JobState.QUEUED)
        queue.enqueue(job)

        # Location ตามมาตรฐาน 202 — บอก client ว่าไปติดตามงานต่อได้ที่ไหน
        response.headers["Location"] = f"/jobs/{job.job_id}"
        log.info("รับใบเสร็จเข้าคิวแล้ว", extra={"job_id": job.job_id, "receipt_id": receipt_id})
        return {"job_id": job.job_id, "state": JobState.QUEUED.value}


def _read_upload(image: UploadFile) -> bytes:
    """อ่านไฟล์จาก request · ใหญ่เกินเพดาน → ตีกลับก่อนอ่านจนหมด

    อ่านทีละก้อนแล้วเช็คขนาดระหว่างทาง เพื่อไม่ให้คนอัปไฟล์ยักษ์กินแรมเซิร์ฟเวอร์
    ก่อนที่ upload_check จะได้ทำงาน
    """
    chunks: list[bytes] = []
    total = 0
    while chunk := image.file.read(1024 * 1024):
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
            raise InputValidationError(f"ไฟล์ใหญ่เกิน {limit_mb} MB กรุณาถ่ายใหม่")
        chunks.append(chunk)
    return b"".join(chunks)


def _require_verified_member(session: Session, tenant_id: str, line_user_id: str) -> Member:
    """ต้องยืนยันเบอร์ + ผูก CRM แล้วเท่านั้นถึงส่งใบเสร็จได้

    ★ กั้นตั้งแต่ประตู ไม่ปล่อยเข้าคิวแล้วไปพังที่ worker — ลูกค้าจะได้รู้ทันที
      ว่าต้องไปยืนยันเบอร์ก่อน (ตรงกับ UX แบบผสม: กั้น OTP ก่อนรับแต้มครั้งแรก)
    """
    member = session.execute(
        select(Member).where(Member.tenant_id == tenant_id, Member.line_user_id == line_user_id)
    ).scalar_one_or_none()

    if member is None or not member.phone_verified or not member.crm_customer_id:
        raise InputValidationError("กรุณายืนยันเบอร์โทรก่อนส่งใบเสร็จ")
    return member
