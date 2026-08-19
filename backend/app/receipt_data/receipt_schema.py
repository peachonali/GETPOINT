"""★ นิยาม field กลาง (Canonical) ของใบเสร็จ — แหล่งความจริงเดียวของทั้งระบบ

ทุกด่านหลัง OCR คุยกันด้วยโครงนี้ ไม่ใช่ dict ลอยๆ:
    field_extractor/template_matcher → Receipt → points → CRM

ไฟล์นี้จะถูก export เป็น TypeScript types อัตโนมัติใน CI
(frontend/src/api/generated-types.ts) เพื่อให้ frontend + backend ใช้สัญญาเดียวกัน
แบบบังคับได้จริง ไม่ใช่เอกสารที่ล้าสมัยเงียบๆ

⚠ field ชื่อ receipt_date ไม่ใช่ date โดยตั้งใจ — ชื่อ date จะไปทับชนิด date
  ที่ import มา ทำให้ไฟล์นี้ import ไม่ได้เลย (เจอตอนต่อ pipeline จริงใน Step 3)
"""
from datetime import date

from pydantic import BaseModel, Field


class Receipt(BaseModel):
    """ใบเสร็จ 1 ใบในรูปแบบกลาง — สิ่งที่ระบบเราสนใจจริงๆ เท่านั้น"""

    tenant_id: str
    #: ชื่อร้านตามที่อ่านได้จากใบเสร็จ
    merchant: str
    #: เลขที่ใบเสร็จ — บางร้านไม่มี (มีผลต่อความแม่นของการกันใบซ้ำ)
    receipt_no: str | None = None
    #: วันที่บนใบเสร็จ (ไม่ใช่วันที่สแกน)
    receipt_date: date | None = None
    #: ★ ยอดที่ใช้คิดแต้ม — ต้องมากกว่า 0 เสมอ (ยอด 0/ติดลบ = อ่านผิดแน่นอน)
    total_amount: float = Field(gt=0)
    #: รหัสสาขา (ถ้าใบเสร็จระบุ) — ส่งต่อให้ CRM ได้
    branch_code: str | None = None
    #: key ของรูปต้นฉบับใน storage — ไว้ย้อนดูหลักฐาน
    source_image_id: str
    #: เวอร์ชัน template ที่ใช้ดึงค่า (Step 5) — ไว้ย้อนสอบว่าตอนนั้นใช้กฎไหน
    template_version: str | None = None
