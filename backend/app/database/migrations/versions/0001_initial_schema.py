"""initial schema: tenants + members

Revision ID: 0001
Revises:
Create Date: 2026-07-27

เขียนด้วยมือ (ไม่ autogenerate) เพราะยังไม่มี Postgres รันตอนสร้าง migration แรก
ต้องตรงกับ app/database/tenants.py + members.py — เทส test_migrations เฝ้าว่าตรงกัน
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=50), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("line_user_id", sa.String(length=100), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("crm_customer_id", sa.String(length=100), nullable=True),
        sa.Column("phone_verified", sa.Boolean(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "line_user_id", name="uq_member_tenant_line_user"),
    )
    op.create_index("ix_members_tenant_id", "members", ["tenant_id"])
    op.create_index("ix_members_phone", "members", ["phone"])


def downgrade() -> None:
    op.drop_index("ix_members_phone", table_name="members")
    op.drop_index("ix_members_tenant_id", table_name="members")
    op.drop_table("members")
    op.drop_table("tenants")
