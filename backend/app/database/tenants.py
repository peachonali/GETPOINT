"""ตาราง tenants — แบรนด์/ลูกค้าของเรา (วันนี้มีแถวเดียว: V-CLUB)

รากของ multi-tenant: ทุกตารางอื่นอ้าง tenant_id กลับมาที่นี่
วันนี้มีแถวเดียวก็จริง แต่มีตารางไว้ตั้งแต่แรกทำให้วันที่มีลูกค้ารายที่ 2
ไม่ต้อง rewrite อะไร (ดู CONTEXT ข้อ 2 — tenant_id ทุกตารางตั้งแต่วันแรก)
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base


class Tenant(Base):
    __tablename__ = "tenants"

    #: id เป็น string อ่านออก เช่น "v-club" ไม่ใช่เลขรัน — เห็นใน log/query แล้วรู้ทันทีว่าใคร
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"Tenant(id={self.id!r}, name={self.name!r})"
