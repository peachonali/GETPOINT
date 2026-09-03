"""ประตู HTTP เรื่องสมัคร/OTP — บางมาก หน้าที่เดียวคือรับ request แล้วส่งต่อ member_service

ทุก endpoint ที่นี่ต้องผ่าน require_line_user ก่อน (ยืนยันว่ามาจาก LINE จริง)
component ของจริง (member_service, verifier) ถูกประกอบไว้ใน main.py แล้วดึงผ่าน app.state
error ที่ member_service/verifier โยน จะถูกแปลงเป็น HTTP โดย exception handler ใน main.py
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.db import get_session
from app.database.members import Member
from app.routes.dependencies import (
    get_line_verifier,
    get_member_service,
    get_tenant_id,
)
from app.member.member_service import MemberService
from app.member.otp_verify import OtpOutcome
from app.observability.logging import get_logger
from app.reliability.errors import AuthenticationError, InputValidationError
from app.security.auth_guard import LineTokenVerifier

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ── สิ่งที่ลูกค้าส่งมาใน body ──
class RequestOtpBody(BaseModel):
    phone: str


class VerifyBody(BaseModel):
    phone: str
    otp: str


def require_line_user(
    authorization: str = Header(default=""),
    verifier: LineTokenVerifier = Depends(get_line_verifier),
) -> str:
    """ยามหน้าประตู — ดึง Bearer token จาก header แล้ว verify กับ LINE คืน lineUserId

    verify ไม่ผ่าน → โยน error → exception handler แปลงเป็น 401/502 (ไม่หลุดมาเป็น 500)
    """
    return verifier.verify(_extract_bearer(authorization))


def _extract_bearer(authorization: str) -> str:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError("ต้องแนบ LINE token มาใน header Authorization: Bearer <token>")
    return token.strip()


# ── endpoints ──
@router.get("/me")
def read_me(
    line_user_id: str = Depends(require_line_user),
    tenant_id: str = Depends(get_tenant_id),
    session: Session = Depends(get_session),
) -> dict:
    """สถานะของคนที่กำลังเปิดแอปอยู่ — หน้าเว็บใช้ตัดสินว่าจะโชว์หน้าสมัครหรือหน้าสแกน

    ★ ถ้าไม่มี endpoint นี้ คนที่ยืนยันเบอร์ไปแล้วจะเจอหน้าสมัครซ้ำทุกครั้งที่เปิดแอป
    ไม่คืนเบอร์เต็มออกไป (PDPA) — หน้าเว็บไม่จำเป็นต้องรู้ ก็แค่ต้องรู้ว่า "ผ่านหรือยัง"
    """
    member = session.execute(
        select(Member).where(Member.tenant_id == tenant_id, Member.line_user_id == line_user_id)
    ).scalar_one_or_none()

    verified = bool(member and member.phone_verified and member.crm_customer_id)
    return {"verified": verified}


@router.post("/request-otp")
def request_otp(
    body: RequestOtpBody,
    _line_user_id: str = Depends(require_line_user),  # ต้อง login LINE แต่ยังไม่ต้องมี record
    service: MemberService = Depends(get_member_service),
) -> dict:
    """ขอ OTP ไปที่เบอร์ · เบอร์ผิดรูป→400 · ขอถี่ไป→429 (จัดการโดย exception handler)"""
    service.request_otp(body.phone)
    return {"status": "otp_sent"}


@router.post("/verify")
def verify(
    body: VerifyBody,
    line_user_id: str = Depends(require_line_user),
    tenant_id: str = Depends(get_tenant_id),
    service: MemberService = Depends(get_member_service),
    session: Session = Depends(get_session),
) -> dict:
    """ยืนยัน OTP แล้วผูกเข้ากับ loga · OTP ผิด/หมดอายุ → 400 พร้อมข้อความที่ลูกค้าเข้าใจ"""
    result = service.verify_and_link(
        session,
        tenant_id=tenant_id,
        line_user_id=line_user_id,
        phone=body.phone,
        otp=body.otp,
    )

    if result.success:
        return {"status": "verified", "crm_customer_id": result.member.crm_customer_id}

    raise InputValidationError(_message_for(result.outcome))


#: แปลงผลยืนยันที่ไม่สำเร็จ → ข้อความที่ลูกค้าอ่านรู้เรื่อง (คนละอันตามสาเหตุ)
_OUTCOME_MESSAGES = {
    OtpOutcome.WRONG: "รหัส OTP ไม่ถูกต้อง",
    OtpOutcome.EXPIRED: "รหัส OTP หมดอายุ กรุณาขอรหัสใหม่",
    OtpOutcome.TOO_MANY_ATTEMPTS: "กรอกผิดหลายครั้งเกินไป กรุณาขอรหัสใหม่",
}


def _message_for(outcome: OtpOutcome) -> str:
    return _OUTCOME_MESSAGES.get(outcome, "ยืนยัน OTP ไม่สำเร็จ")
