"""ตั้งค่ากลางของเทส (fixtures ที่ใช้ร่วม)

db_session: ฐานข้อมูล SQLite in-memory ใหม่ต่อ 1 เทส — เร็ว, สะอาด, ไม่ต้องมี Postgres
"""
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.database.db import Base

# ต้อง import ทุก model ก่อน create_all เพื่อให้ Base.metadata รู้จักทุกตาราง
# (import เพื่อ side-effect ของการลงทะเบียน model — ไม่ได้เรียกใช้ชื่อตรงๆ)
from app.database import members, receipts, tenants  # noqa: F401


@pytest.fixture
def db_engine(tmp_path) -> Engine:
    """engine ของ DB ทดสอบ — SQLite ไฟล์ชั่วคราว ใหม่หมดจดต่อ 1 เทส

    ★★ ทำไมเป็น "ไฟล์" ไม่ใช่ ":memory:" (เปลี่ยนมาจากของเดิม อย่าเปลี่ยนกลับ)
      ของเดิมใช้ `:memory:` + StaticPool ซึ่งบังคับให้ทุก session ใช้ connection
      ตัวเดียวกัน → ข้อมูลที่ยัง "ไม่ commit" มองเห็นได้จาก session อื่นด้วย
      ซึ่ง **ไม่ตรงกับ Postgres ของจริง** และทำให้เทสเขียวทั้งที่ระบบพัง

      เจอจริง: ทดลองเปลี่ยน session.commit() เป็น session.flush() ใน scan_job
      (= แถวใบเสร็จจะหายเมื่อ worker ปิด session โดยไม่ commit → ลูกค้าได้แต้มซ้ำ)
      แล้วเทสทั้ง 328 ข้อยังเขียวหมด เพราะ fixture ไม่บังคับกฎเดียวกับของจริง

      ไฟล์จริงมี connection แยกต่อ session → transaction แยกกันจริง เหมือน Postgres
      check_same_thread=False ยังจำเป็นอยู่ (FastAPI TestClient รัน route คนละเธรด)
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(db_engine) -> Iterator[Session]:
    """session ผูกกับ SQLite in-memory ที่มีสคีมาครบทุกตาราง · DB ใหม่หมดจดต่อเทส"""
    with Session(db_engine) as session:
        yield session
