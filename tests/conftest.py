"""ตั้งค่ากลางของเทส (fixtures ที่ใช้ร่วม)

db_session: ฐานข้อมูล SQLite in-memory ใหม่ต่อ 1 เทส — เร็ว, สะอาด, ไม่ต้องมี Postgres
    (นี่คือเหตุผลที่ db.py แยก create_db_engine ออกมา — ดู ADR 0004)
"""
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.database.db import Base, create_db_engine

# ต้อง import ทุก model ก่อน create_all เพื่อให้ Base.metadata รู้จักทุกตาราง
# (import เพื่อ side-effect ของการลงทะเบียน model — ไม่ได้เรียกใช้ชื่อตรงๆ)
from app.database import members, tenants  # noqa: F401


@pytest.fixture
def db_session() -> Iterator[Session]:
    """session ผูกกับ SQLite in-memory ที่มีสคีมาครบทุกตาราง

    แต่ละเทสได้ DB ใหม่หมดจด — เทสไม่กวนกันผ่านข้อมูลค้าง
    """
    engine = create_db_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
