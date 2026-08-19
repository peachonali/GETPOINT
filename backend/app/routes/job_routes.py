"""GET /jobs/{id} — ถามว่างานสแกนถึงไหนแล้ว

หน้า ProcessingScreen ถามซ้ำเป็นระยะจนกว่างานจะเสร็จ
(ช่องทางหลักในการแจ้งผลคือ LINE Push — ตัวนี้ไว้ให้คนที่ยังเปิดหน้าค้างอยู่เห็นความคืบหน้า)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.jobs.job_status import JobStatusStore
from app.reliability.errors import InputValidationError
from app.routes.auth_routes import require_line_user
from app.routes.dependencies import get_job_status

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}")
def read_job(
    job_id: str,
    _line_user_id: str = Depends(require_line_user),  # ต้องเป็นผู้ใช้ LINE จริงถึงถามได้
    status_store: JobStatusStore = Depends(get_job_status),
) -> dict:
    """คืนสถานะงาน · ไม่พบ (หมดอายุ/ไม่เคยมี) → 400 พร้อมข้อความที่ลูกค้าเข้าใจ"""
    status = status_store.get(job_id)
    if status is None:
        raise InputValidationError("ไม่พบรายการนี้แล้ว (อาจหมดอายุ) กรุณาส่งใบเสร็จใหม่")

    return {
        "job_id": status.job_id,
        "state": status.state.value,
        "message": status.message,
        "points_balance": status.points_balance,
    }
