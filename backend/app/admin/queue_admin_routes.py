"""หน้า admin — ดูสุขภาพระบบ + จัดการใบที่ค้าง (dead letter) + export Excel

★ ทำให้งานเบื้องหลังที่สร้างไว้ (metrics / dead_letter / excel_export) "ใช้งานได้จริง"
  โดยคน — ไม่งั้นมันเป็นแค่โค้ดที่ไม่มีใครเรียก

ทุก endpoint ผ่าน require_admin (โทเคนลับใน env) — ดู security/admin_guard
ใช้ tenant เดียว (default) ในเฟสนี้ · วันมีหลายแบรนด์ค่อยรับ tenant จาก path/token
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.database.db import get_session
from app.observability.metrics import scan_metrics
from app.routes.dependencies import get_formula_id, get_image_store, get_tenant_id
from app.security.admin_guard import require_admin
from app.send_queue.dead_letter import list_dead, revive
from app.send_queue.excel_export import export_unsent

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/metrics")
def get_metrics(
    since_days: int = 7,
    tenant_id: str = Depends(get_tenant_id),
    session: Session = Depends(get_session),
) -> dict:
    """ภาพรวมการสแกน N วันล่าสุด — ให้ทีมดูแลเห็นสุขภาพระบบในตาเดียว"""
    m = scan_metrics(session, tenant_id, since_days=since_days)
    return {
        "since_days": m.since_days,
        "awarded": m.awarded,
        "pending": m.pending,
        "failed": m.failed,
        "dead": m.dead,
        "rejected": m.rejected,
        "award_rate": round(m.award_rate, 3),
        "needs_attention": m.needs_attention,  # มีใบ DEAD ค้างต้องกู้ไหม
    }


@router.get("/dead-letter")
def get_dead_letter(
    tenant_id: str = Depends(get_tenant_id),
    session: Session = Depends(get_session),
) -> dict:
    """ใบที่ระบบยอมแพ้แล้ว (ส่งแต้มไม่สำเร็จเกินเกณฑ์) — ต้องมีคนตัดสิน"""
    view = list_dead(session, tenant_id)
    return {
        "dead_count": view.dead_count,
        "still_retrying_count": view.still_retrying_count,
        "receipts": [
            {
                "id": r.id,
                "amount": r.total_amount,
                "merchant": r.merchant,
                "reference": r.crm_reference,
                "attempts": r.send_attempts,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in view.records
        ],
    }


@router.post("/dead-letter/{receipt_id}/revive")
def revive_dead_letter(
    receipt_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """ปลุกใบที่ค้างกลับเข้าคิวส่งซ้ำ (หลังคนแก้ต้นเหตุแล้ว)

    revive คืน False ถ้าใบไม่ได้อยู่สถานะ DEAD — กันเผลอปลุกใบที่ได้แต้มแล้ว
    """
    revived = revive(session, receipt_id)
    return {"revived": revived}


@router.get("/export.xlsx")
def export_unsent_points(
    tenant_id: str = Depends(get_tenant_id),
    formula_id: str = Depends(get_formula_id),
    session: Session = Depends(get_session),
) -> Response:
    """ดาวน์โหลดใบที่ยังไม่ได้แต้ม (FAILED/PENDING/DEAD) เป็น Excel — disaster recovery

    ไฟล์นี้เอาไปอัปโหลดเข้าหน้า Import ของ loga ได้ตรงๆ เมื่อ API ล่มยาว
    """
    result = export_unsent(session, tenant_id, formula_id=formula_id)
    return Response(
        content=result.content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="unsent_points.xlsx"'},
    )
