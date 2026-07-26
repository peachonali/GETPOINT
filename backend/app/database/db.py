"""เชื่อมต่อฐานข้อมูล + จัดการ session (sync SQLAlchemy 2.0)

★ ทำไม sync ไม่ใช่ async (ดู ADR 0004):
    ที่ < 2 RPS + งานหนักอยู่ใน worker คนละ process แล้ว async ไม่ให้ throughput
    เพิ่มที่รู้สึกได้ แต่แลกด้วยความซับซ้อนตอน debug (stack trace ยาว, ต้องระวัง
    await ทุกจุด, ไลบรารีบางตัวไม่รองรับ) — ทีมเล็กจ่ายไม่คุ้ม

★ ทำไมแยก create_db_engine ออกมาเป็นฟังก์ชัน:
    เทสสร้าง engine SQLite ในหน่วยความจำของตัวเองได้ โดยไม่ต้องพึ่ง Postgres/docker
    (ดู tests/conftest.py) — prod ใช้ Postgres, เทสใช้ SQLite ด้วยโค้ดชุดเดียวกัน

⚠ ตราบใดที่ยังไม่ตั้ง DATABASE_URL: engine/SessionLocal เป็น None โดยตั้งใจ
   ระบบต้อง "พังตอนใช้จริงด้วย error ที่ชัด" ไม่ใช่ "พัง import ทั้งระบบ" ตอนบูต
   (เครื่อง dev/CI ที่ยังไม่ตั้ง DB จะได้ import ไฟล์อื่นมาเทสได้)
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config.settings import settings


class Base(DeclarativeBase):
    """ฐานของทุก ORM model — tenants / members / receipts / ... สืบทอดตัวนี้

    รวม metadata ของทุกตารางไว้ที่เดียว → Alembic autogenerate เห็นครบ
    และเทสเรียก Base.metadata.create_all(engine) สร้างสคีมาทั้งหมดได้ในบรรทัดเดียว
    """


def create_db_engine(url: str) -> Engine:
    """สร้าง engine จาก connection string — แยกไว้เพื่อให้เทสสร้าง engine ของตัวเองได้

    pool_pre_ping=True: เช็คว่า connection ยังไม่ตายก่อนหยิบมาใช้ทุกครั้ง
        กัน "server closed the connection" หลัง Postgres restart หรือ idle timeout
        (ราคาถูกมากที่ volume เรา — ping หนึ่งครั้งต่อการหยิบ connection)
    check_same_thread=False: สำหรับ SQLite เท่านั้น — web รัน route ใน threadpool
        session อาจถูกแตะข้ามเธรด · Postgres ไม่มีข้อจำกัดนี้
    """
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


# ── engine + session factory ระดับ process (ประกอบครั้งเดียวจาก settings) ──
# create_engine ไม่เปิด connection จริงจนกว่าจะ query แรก → ปลอดภัยแม้ DB ยังไม่ขึ้น
# แต่ url ว่างสร้าง engine ไม่ได้ จึงปล่อย None ไว้ (ดูเหตุผลใน docstring หัวไฟล์)
engine: Engine | None = create_db_engine(settings.database_url) if settings.database_url else None
SessionLocal: sessionmaker[Session] | None = (
    sessionmaker(bind=engine, expire_on_commit=False) if engine else None
)


def get_session() -> Iterator[Session]:
    """FastAPI dependency — ยืม session 1 ตัวต่อ 1 request แล้วปิดเสมอ

    ใช้แบบ: def route(..., db: Session = Depends(get_session))
    การ commit/rollback เป็นหน้าที่ของชั้น service ไม่ใช่ที่นี่ (ที่นี่แค่ยืม-คืน)
    """
    if SessionLocal is None:
        raise RuntimeError("ยังไม่ได้ตั้ง DATABASE_URL ใน .env — เชื่อมฐานข้อมูลไม่ได้")

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
