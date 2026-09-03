"""เทส app/database/db.py

ใช้ SQLite in-memory ล้วน — พิสูจน์ว่า engine/session ทำงานจริงโดยไม่ต้องมี Postgres
(นี่คือเหตุผลที่ create_db_engine ถูกแยกเป็นฟังก์ชัน — ดู ADR 0004)
Postgres path เป็นแค่ if url.startswith("sqlite") จึงเชื่อตามโค้ด ไม่ลาก driver มาเทส
"""
from sqlalchemy import Column, Integer, MetaData, String, Table, text
from sqlalchemy.orm import sessionmaker

from app.database.db import Base, create_db_engine


def test_sqlite_engine_connects():
    engine = create_db_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1


def test_session_can_round_trip():
    """เปิด session → insert → commit → อ่านกลับได้ = plumbing ครบวง"""
    engine = create_db_engine("sqlite:///:memory:")
    metadata = MetaData()
    sample = Table(
        "sample", metadata,
        Column("id", Integer, primary_key=True),
        Column("value", String),
    )
    metadata.create_all(engine)

    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        session.execute(sample.insert().values(id=1, value="ok"))
        session.commit()
        result = session.execute(text("SELECT value FROM sample WHERE id = 1")).scalar()

    assert result == "ok"


def test_base_exposes_metadata_for_migrations():
    """Base ต้องมี metadata ให้ Alembic autogenerate + Base.metadata.create_all ใช้ได้"""
    assert hasattr(Base, "metadata")
    assert Base.metadata.tables is not None
