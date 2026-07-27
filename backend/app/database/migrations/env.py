"""Alembic environment — ผูก migration เข้ากับ Base.metadata ของโปรเจกต์

url มาจาก settings.database_url (แหล่งเดียว) แต่เทส override ได้ผ่าน
config.set_main_option("sqlalchemy.url", ...) → รัน migration บน SQLite ชั่วคราวได้
"""
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

from app.config.settings import settings
from app.database.db import Base

# ต้อง import ทุก model ก่อน เพื่อให้ Base.metadata เห็นทุกตาราง
# (import เพื่อ side-effect การลงทะเบียน model — autogenerate จะได้เทียบครบ)
from app.database import members, tenants  # noqa: F401

config = context.config

# ถ้ายังไม่มี url (เทสไม่ได้ set) → ดึงจาก settings ที่เดียว
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """โหมด offline — ออกเป็น SQL อย่างเดียว ไม่ต่อ DB จริง"""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """โหมด online — ต่อ DB จริงแล้วรัน

    render_as_batch=True: SQLite ไม่รองรับ ALTER TABLE เต็มรูป → batch mode สร้าง
    ตารางใหม่แล้วคัดลอกข้อมูลแทน · ทำให้ migration เดียวกันรันได้ทั้ง SQLite (เทส)
    และ Postgres (prod)
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
