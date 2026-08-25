"""receipts: ประวัติใบเสร็จ (จำเป็นสำหรับการกันใบซ้ำ)

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-24

เขียนด้วยมือให้ตรงกับ app/database/receipts.py — เทส test_migrations เฝ้าว่าตรงกัน

★ ทำไมเพิ่งมามีตอนนี้: ก่อนหน้านี้ระบบไม่เคยจำว่ารับใบไหนไปแล้ว
  → ลูกค้าถ่ายใบเดิมส่งซ้ำแล้วได้แต้มทุกครั้ง (ดู docs/decisions/0006)
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "receipts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("image_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("merchant", sa.String(length=200), nullable=True),
        sa.Column("receipt_no", sa.String(length=100), nullable=True),
        sa.Column("receipt_date", sa.Date(), nullable=True),
        sa.Column("receipt_time", sa.Time(), nullable=True),
        sa.Column("total_amount", sa.Float(), nullable=False),
        sa.Column("reference_codes", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("crm_reference", sa.String(length=100), nullable=True),
        sa.Column("points_awarded", sa.Integer(), nullable=True),
        sa.Column("source_image_id", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # ★ ตาข่ายรับระดับฐานข้อมูล — เผื่อ worker สองตัวทำใบเดียวกันพร้อมกัน
        #   โค้ดตรวจก่อนเขียนอยู่แล้ว แต่ระหว่าง "ตรวจ" กับ "เขียน" มีช่องให้แทรกได้เสมอ
        sa.UniqueConstraint("tenant_id", "content_fingerprint", name="uq_receipt_content"),
    )
    op.create_index("ix_receipts_tenant_id", "receipts", ["tenant_id"])
    op.create_index("ix_receipts_member_id", "receipts", ["member_id"])
    op.create_index("ix_receipts_image_fingerprint", "receipts", ["image_fingerprint"])
    op.create_index("ix_receipts_lookup", "receipts", ["tenant_id", "member_id", "total_amount"])
    op.create_index("ix_receipts_tenant_amount", "receipts", ["tenant_id", "total_amount"])


def downgrade() -> None:
    op.drop_index("ix_receipts_tenant_amount", table_name="receipts")
    op.drop_index("ix_receipts_lookup", table_name="receipts")
    op.drop_index("ix_receipts_image_fingerprint", table_name="receipts")
    op.drop_index("ix_receipts_member_id", table_name="receipts")
    op.drop_index("ix_receipts_tenant_id", table_name="receipts")
    op.drop_table("receipts")
