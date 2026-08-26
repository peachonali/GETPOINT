"""ประตู HTTP เรื่องแต้ม — ให้ลูกค้าดูแต้มสะสม + ประวัติใบเสร็จของตัวเอง

★ ทำไมมี endpoint นี้ (ปิดวงจรที่ลูกค้าเห็น):
  สแกน → รอผล → ★ เปิดมาดูแต้มสะสม/ประวัติได้เอง
  ถ้าไม่มี ลูกค้าเห็นแต้มแค่ตอน LINE Push แจ้งครั้งเดียว แล้วย้อนดูไม่ได้เลย

★ แต้มสะสม "สด" มาจาก CRM (loga) ไม่ใช่ผลรวมในตารางเรา:
  loga เป็นเจ้าของยอดแต้มจริง (ลูกค้าอาจใช้แต้มที่อื่น/ได้แต้มจากช่องทางอื่น)
  เราถามยอดล่าสุดจาก loga เสมอ · ตาราง receipts ของเราเก็บแค่ "ใบที่ผ่านระบบเรา"

★ ประวัติแสดงเฉพาะใบของ "คนที่ล็อกอินอยู่" เท่านั้น — กันดูของคนอื่น
  กรองด้วย member_id ของ line_user นั้นตรงๆ ไม่รับ id จาก client
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.db import get_session
from app.database.members import Member
from app.database.receipts import STATUS_AWARDED, ReceiptRecord
from app.external.crm_interface import CrmPort
from app.observability.logging import get_logger
from app.reliability.errors import ExternalServiceError, InputValidationError
from app.routes.auth_routes import require_line_user
from app.routes.dependencies import get_crm, get_tenant_id

log = get_logger(__name__)

router = APIRouter(prefix="/points", tags=["points"])

#: แสดงประวัติล่าสุดกี่ใบ — พอสำหรับ "ดูย้อนหลังล่าสุด" ไม่ต้องโหลดทั้งชีวิต
_HISTORY_LIMIT = 20


@router.get("/me")
def read_my_points(
    line_user_id: str = Depends(require_line_user),
    tenant_id: str = Depends(get_tenant_id),
    session: Session = Depends(get_session),
    crm: CrmPort = Depends(get_crm),
) -> dict:
    """แต้มสะสมล่าสุด (จาก CRM) + ประวัติใบเสร็จล่าสุดของคนที่ล็อกอินอยู่"""
    member = _require_member(session, tenant_id, line_user_id)

    return {
        "points_balance": _fetch_balance(crm, member),
        "history": _recent_history(session, member.id),
    }


def _require_member(session: Session, tenant_id: str, line_user_id: str) -> Member:
    member = session.execute(
        select(Member).where(Member.tenant_id == tenant_id, Member.line_user_id == line_user_id)
    ).scalar_one_or_none()

    if member is None or not member.crm_customer_id:
        # ยังไม่ยืนยันเบอร์/ผูก CRM = ยังไม่มีแต้มให้ดู — บอกให้ไปยืนยันก่อน
        raise InputValidationError("กรุณายืนยันเบอร์โทรก่อนดูแต้มสะสม")
    return member


def _fetch_balance(crm: CrmPort, member: Member) -> int | None:
    """ถามยอดแต้มล่าสุดจาก CRM · CRM ล่ม → คืน None (ยังโชว์ประวัติได้)

    ★ ไม่ให้ CRM ล่มทำทั้งหน้าพัง — ประวัติในตารางเรายังแสดงได้
      ลูกค้าเห็น "แต้มสะสม: กำลังโหลด" ดีกว่าเห็นหน้า error ทั้งหน้า
    """
    try:
        customer = crm.find_customer(member.phone) if member.phone else None
        return customer.points_balance if customer else None
    except ExternalServiceError as exc:
        log.warning("ดึงยอดแต้มจาก CRM ไม่สำเร็จ", extra={"detail": str(exc)})
        return None


def _recent_history(session: Session, member_id: int) -> list[dict]:
    """ใบเสร็จที่ได้แต้มแล้วล่าสุดของสมาชิกคนนี้"""
    rows = session.scalars(
        select(ReceiptRecord)
        .where(ReceiptRecord.member_id == member_id)
        .where(ReceiptRecord.status == STATUS_AWARDED)
        .order_by(ReceiptRecord.created_at.desc())
        .limit(_HISTORY_LIMIT)
    )
    return [
        {
            "merchant": r.merchant,
            "amount": r.total_amount,
            "points": r.points_awarded,
            "date": r.receipt_date.isoformat() if r.receipt_date else None,
        }
        for r in rows
    ]
