"""ตั้งค่ากลางของเทส (fixtures ที่ใช้ร่วม)

db_session: ฐานข้อมูล SQLite in-memory ใหม่ต่อ 1 เทส — เร็ว, สะอาด, ไม่ต้องมี Postgres
"""
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.db import Base

# ต้อง import ทุก model ก่อน create_all เพื่อให้ Base.metadata รู้จักทุกตาราง
# (import เพื่อ side-effect ของการลงทะเบียน model — ไม่ได้เรียกใช้ชื่อตรงๆ)
from app.database import members, tenants  # noqa: F401


@pytest.fixture
def db_session() -> Iterator[Session]:
    """session ผูกกับ SQLite in-memory ที่มีสคีมาครบทุกตาราง · DB ใหม่หมดจดต่อเทส

    ★ ใช้ StaticPool + :memory: โดยเจตนา:
      SQLite :memory: ปกติแยก DB ต่อ connection → connection ใหม่ = DB ว่าง ไม่มี table
      StaticPool บังคับใช้ connection "ตัวเดียว" แชร์ทุกที่ → table ที่ create ไว้อยู่ครบ
      แม้ถูกแตะจากคนละเธรด (จำเป็นสำหรับ FastAPI TestClient ที่รัน route ในเธรดอื่น)
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
