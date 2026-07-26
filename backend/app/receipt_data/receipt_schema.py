"""★ นิยาม field กลาง (Canonical) ของใบเสร็จ — แหล่งความจริงเดียว
ไฟล์นี้จะถูก export เป็น TypeScript types อัตโนมัติใน CI (frontend/src/api/generated-types.ts)
เพื่อให้ frontend + backend ใช้สัญญาเดียวกันแบบบังคับได้จริง (ไม่ใช่เอกสาร .md)"""
from pydantic import BaseModel
from datetime import date


class Receipt(BaseModel):
    tenant_id: str
    merchant: str
    receipt_no: str | None = None
    date: date | None = None
    total_amount: float
    branch_code: str | None = None
    source_image_id: str
    template_version: str | None = None
