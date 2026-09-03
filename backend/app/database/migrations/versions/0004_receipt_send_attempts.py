"""receipts.send_attempts: นับครั้งที่พยายามส่งแต้มแล้วโดนปฏิเสธเฉพาะใบนี้

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-25

ใช้ตัดสินว่าใบไหน "ส่งไม่ได้จริงๆ" (loga ปฏิเสธซ้ำๆ เฉพาะใบนี้) → ย้ายไปสถานะ DEAD
เพื่อไม่ให้ใบที่พังตลอดไปบล็อกคิวส่งซ้ำของใบอื่น (ดู send_queue.py)
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "receipts",
        sa.Column("send_attempts", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("receipts", "send_attempts")
