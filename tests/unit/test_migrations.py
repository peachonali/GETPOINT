"""เทส Alembic migration — พิสูจน์ว่ารันจริงได้ + schema ตรงกับ model

ใช้ SQLite ไฟล์ชั่วคราว (ไม่ใช่ :memory: เพราะ Alembic เปิด connection ใหม่ต่อคำสั่ง
ทำให้ :memory: หาย) · เทสนี้กัน 2 อย่าง:
  1. migration รันไม่ได้ (env.py/config พัง) — จะรู้ทันทีไม่ใช่ตอน deploy
  2. migration drift จาก model — schema ที่ migrate ได้ต้องตรงกับที่ model ประกาศ
"""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.database.members import Member
from app.database.receipts import ReceiptRecord
from app.database.tenants import Tenant

# tests/unit/test_migrations.py → ขึ้น 2 ชั้นถึง repo root → backend/alembic.ini
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "backend" / "alembic.ini"


def _alembic_config(url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url)  # override ให้ชี้ SQLite ชั่วคราว
    return config


def _sqlite_url(tmp_path) -> str:
    return f"sqlite:///{tmp_path / 'migration_test.db'}"


def test_upgrade_head_creates_all_tables(tmp_path):
    url = _sqlite_url(tmp_path)
    command.upgrade(_alembic_config(url), "head")

    tables = set(inspect(create_engine(url)).get_table_names())
    assert {"tenants", "members", "receipts"} <= tables


def test_downgrade_removes_all_tables(tmp_path):
    """downgrade ต้องย้อนได้สะอาด — ไม่งั้น rollback ตอน deploy พังจะกู้ไม่ได้"""
    url = _sqlite_url(tmp_path)
    config = _alembic_config(url)

    command.upgrade(config, "head")
    command.downgrade(config, "base")

    tables = set(inspect(create_engine(url)).get_table_names())
    assert "tenants" not in tables
    assert "members" not in tables
    assert "receipts" not in tables


def test_migration_schema_matches_models(tmp_path):
    """★ กัน drift: คอลัมน์ที่ migration สร้าง ต้องตรงกับที่ model ประกาศเป๊ะ
    ถ้าใครเพิ่ม field ใน model แล้วลืมเขียน migration เทสนี้จะแดง"""
    url = _sqlite_url(tmp_path)
    command.upgrade(_alembic_config(url), "head")
    inspector = inspect(create_engine(url))

    for model in (Tenant, Member, ReceiptRecord):
        migrated_columns = {col["name"] for col in inspector.get_columns(model.__tablename__)}
        model_columns = {col.name for col in model.__table__.columns}
        assert migrated_columns == model_columns, f"{model.__tablename__} schema ไม่ตรงกับ model"
