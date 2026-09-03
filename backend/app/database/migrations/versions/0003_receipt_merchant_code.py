"""receipts.merchant_code: รหัสร้านที่คงที่ (ใช้ตัดสินใจแทนชื่อร้าน)

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-24

ทำไมต้องมีคอลัมน์นี้ทั้งที่มี merchant (ชื่อร้าน) อยู่แล้ว:
ชื่อร้านมาจาก OCR ซึ่งอ่านได้ไม่คงที่ระหว่างรูปของใบเดียวกัน จึงใช้ตัดสินใจไม่ได้
ส่วนรหัสร้านมาจากเลขผู้เสียภาษี (วัดจริง 27/28 ถูก · ผิด 0) — ใช้ตัดสินใจได้
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("receipts", sa.Column("merchant_code", sa.String(length=50), nullable=True))
    # duplicate_check กรองด้วย tenant + ยอด ก่อนเสมอ แล้วค่อยเทียบร้านในหน่วยความจำ
    # จึงยังไม่ต้องมี index ของ merchant_code (เพิ่มเมื่อมีรายงานต่อร้านที่ช้าจริง)


def downgrade() -> None:
    op.drop_column("receipts", "merchant_code")
