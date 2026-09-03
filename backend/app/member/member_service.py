"""ตัวคุมภาพรวมของสมาชิก — ร้อย OTP + member + loga เข้าด้วยกัน

2 งานที่ให้ route เรียก:
    request_otp(phone)              ขอ OTP (กันสแปม → สุ่ม → เก็บ → ส่ง SMS)
    verify_and_link(...)            ยืนยัน OTP แล้วผูกเข้ากับ loga

รับทุก dependency ผ่าน constructor (DI) — เทสยัดของปลอมได้ครบ, prod ยัดของจริง
ไม่สร้าง session เอง: session มาต่อ 1 request จาก route (Depends(get_session))
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.members import Member
from app.external.sms_interface import SmsPort
from app.member.member_link import MemberLinker
from app.member.otp_generate import generate_otp
from app.member.otp_store import OtpStore
from app.member.otp_verify import OtpOutcome, verify_otp
from app.member.phone_normalize import normalize_phone
from app.observability.logging import get_logger, log_context
from app.reliability.errors import RateLimitedError
from app.security.rate_limit import RateLimiter

log = get_logger(__name__)


@dataclass(frozen=True)
class VerifyResult:
    """ผลของการยืนยัน+ผูก — route แปลงเป็น response/ข้อความให้ลูกค้า"""

    outcome: OtpOutcome
    member: Member | None = None

    @property
    def success(self) -> bool:
        return self.outcome is OtpOutcome.OK


class MemberService:
    def __init__(
        self,
        *,
        otp_store: OtpStore,
        sms: SmsPort,
        linker: MemberLinker,
        otp_rate_limiter: RateLimiter,
    ) -> None:
        self._otp_store = otp_store
        self._sms = sms
        self._linker = linker
        self._otp_rate = otp_rate_limiter

    def request_otp(self, phone: str) -> None:
        """ขอ OTP ใหม่ให้เบอร์นี้ · ถี่เกินเพดาน → RateLimitedError

        normalize เบอร์ที่นี่ (จุดเข้า domain) เพื่อให้ทั้ง key rate-limit, key เก็บ OTP
        และตอน verify ใช้เบอร์รูปเดียวกันเป๊ะ — ถ้า save ด้วยรูปหนึ่ง verify อีกรูป จะไม่ match
        """
        phone = normalize_phone(phone)

        limit = self._otp_rate.hit(f"otp_request:{phone}")
        if not limit.allowed:
            # กันเผา SMS (แต่ละข้อความมีค่าเงิน) — ยกเลิกก่อนสุ่ม/ส่ง
            raise RateLimitedError(limit.retry_after_seconds)

        otp = generate_otp()
        self._otp_store.save(phone, otp)
        self._sms.send_otp(phone, otp)

        log.info("ส่ง OTP แล้ว", extra={"phone": phone})  # phone ถูก mask, otp ไม่ log

    def verify_and_link(
        self, session: Session, *, tenant_id: str, line_user_id: str, phone: str, otp: str
    ) -> VerifyResult:
        """ยืนยัน OTP แล้วผูกสมาชิกเข้ากับ loga

        ★ จงใจแยกเป็น 2 commit เพื่อทนต่อ loga ล่ม:
          commit 1 — OTP ผ่าน → เก็บ phone + phone_verified=True (เบอร์ยืนยันแล้ว persist)
          commit 2 — linker.link ผูก loga (อยู่ใน link)
          ถ้า loga ล่มหลัง commit 1: ลูกค้าไม่ต้อง OTP ใหม่ แค่ retry link ได้
          (member_link idempotent รองรับ) · link ที่พังจะโยน error ให้ route จัดการต่อ
        """
        phone = normalize_phone(phone)

        outcome = verify_otp(self._otp_store, phone, otp)
        if outcome is not OtpOutcome.OK:
            return VerifyResult(outcome=outcome)

        member = self._get_or_create_member(session, tenant_id, line_user_id)
        member.phone = phone
        member.phone_verified = True
        session.commit()  # commit 1 — เบอร์ยืนยันแล้ว ต้องไม่หายแม้ link พังต่อ

        self._linker.link(session, member)  # commit 2 (ภายใน) — ผูก loga

        with log_context(tenant_id=tenant_id):
            log.info("สมาชิกยืนยันเบอร์และผูก CRM แล้ว")
        return VerifyResult(outcome=OtpOutcome.OK, member=member)

    @staticmethod
    def _get_or_create_member(session: Session, tenant_id: str, line_user_id: str) -> Member:
        """หาสมาชิกเดิมจาก (tenant_id, line_user_id) · ไม่มีก็สร้างใหม่

        คนเดิมที่เคยแอด LINE แล้วเพิ่งมายืนยันเบอร์ = มี record อยู่แล้ว (สร้างตอนแอด)
        แต่รองรับกรณีมายืนยันเลยโดยยังไม่มี record ด้วย → สร้างให้
        """
        member = session.execute(
            select(Member).where(
                Member.tenant_id == tenant_id, Member.line_user_id == line_user_id
            )
        ).scalar_one_or_none()

        if member is None:
            member = Member(tenant_id=tenant_id, line_user_id=line_user_id)
            session.add(member)

        return member
