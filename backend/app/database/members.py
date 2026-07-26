"""ตาราง members — สมาชิกหนึ่งคนในสายตาระบบเรา

★ ตารางนี้เก็บ "ข้อมูลส่วนบุคคล" (เบอร์ + LINE ID) → อยู่ในขอบเขต PDPA
   เก็บเท่าที่จำเป็นจริง (ยังไม่เก็บชื่อ/อีเมล/ที่อยู่ — เพิ่มเมื่อมี use case)

★ เส้นทางข้อมูล 1 คน:
   แอด LINE → ได้ line_user_id (ยังไม่มี phone)
   → ยืนยัน OTP → เติม phone + phone_verified=True
   → ผูก loga สำเร็จ → เติม crm_customer_id
   ทั้งหมดผูก tenant_id เดียว
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base


class Member(Base):
    __tablename__ = "members"
    __table_args__ = (
        # 1 LINE user = 1 สมาชิก ต่อ 1 แบรนด์ — กันสมัครซ้ำจากการแอดใหม่/กดซ้ำ
        UniqueConstraint("tenant_id", "line_user_id", name="uq_member_tenant_line_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    #: multi-tenant — index เพราะ query เกือบทั้งหมดกรองด้วย tenant_id
    tenant_id: Mapped[str] = mapped_column(String(50), index=True)

    #: มาจาก LIFF (LINE Login) — ตัวระบุคนแรกสุด ก่อนรู้เบอร์ด้วยซ้ำ
    line_user_id: Mapped[str] = mapped_column(String(100))

    #: เบอร์รูป canonical (ดู phone_normalize) · ว่างจนกว่ายืนยัน OTP
    #: index เพราะ member_link ค้นสมาชิกด้วยเบอร์เวลาเชื่อม loga
    phone: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)

    #: รหัสสมาชิกฝั่ง loga (uid หรือ "P"+pcard_id) · ว่างจนกว่าผูกสำเร็จ
    crm_customer_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    #: ผ่าน OTP แล้วหรือยัง — ก่อนเป็น True ห้ามส่งแต้มเข้า loga (ยังไม่ยืนยันตัวตน)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        # ไม่ใส่ phone ใน repr — กันเบอร์หลุดไป log โดยไม่ผ่าน mask (PDPA)
        return f"Member(id={self.id}, tenant_id={self.tenant_id!r}, verified={self.phone_verified})"
