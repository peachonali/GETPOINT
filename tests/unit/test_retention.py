"""เทส app/maintenance/retention.py — ลบรูปเก่าตามกำหนด PDPA

★ กฎที่ต้องพิสูจน์:
    - ลบเฉพาะรูปที่เก่ากว่ากำหนด · รูปใหม่ต้องอยู่ครบ
    - แถว receipts ยังอยู่ (เพื่อกันใบซ้ำต่อ) — ลบแค่ตัวรูป
    - รันซ้ำได้ ไม่ลบซ้ำ/ไม่พังถ้าไฟล์หายไปแล้ว
"""
from datetime import date, datetime, timedelta

import pytest

from app.database.members import Member
from app.database.receipts import STATUS_AWARDED, ReceiptRecord
from app.database.tenants import Tenant
from app.maintenance.retention import purge_old_images
from app.storage.image_store import ImageStore
from app.storage.local_storage import LocalStorage

TENANT = "v-club"
TODAY = date(2026, 6, 30)


@pytest.fixture
def member_id(db_session) -> int:
    db_session.add(Tenant(id=TENANT, name="V-CLUB"))
    m = Member(tenant_id=TENANT, line_user_id="U1", crm_customer_id="C1")
    db_session.add(m)
    db_session.commit()
    return m.id


@pytest.fixture
def images(tmp_path) -> ImageStore:
    return ImageStore(LocalStorage(tmp_path / "storage"))


def _add(session, member_id, images, *, receipt_id, days_old):
    """สร้างแถว + รูปจริง แล้วตั้ง created_at ให้เก่าตามต้องการ"""
    key = images.put(TENANT, receipt_id, b"\xff\xd8\xff-pretend-jpeg")
    record = ReceiptRecord(
        tenant_id=TENANT, member_id=member_id,
        content_fingerprint=f"fp-{receipt_id}", image_fingerprint="img",
        merchant="ร้าน", total_amount=100.0, reference_codes=[],
        status=STATUS_AWARDED, source_image_id=key,
        created_at=datetime.combine(TODAY - timedelta(days=days_old), datetime.min.time()),
    )
    session.add(record)
    session.commit()
    return record, key


def test_deletes_only_old_images(db_session, member_id, images):
    old_rec, old_key = _add(db_session, member_id, images, receipt_id="old", days_old=100)
    new_rec, new_key = _add(db_session, member_id, images, receipt_id="new", days_old=10)

    result = purge_old_images(db_session, images, retention_days=90, today=TODAY)

    assert result.images_deleted == 1
    assert not images._storage.exists(old_key), "รูปเก่าต้องถูกลบ"
    assert images._storage.exists(new_key), "รูปใหม่ต้องอยู่"


def test_keeps_receipt_row_for_duplicate_check(db_session, member_id, images):
    """★ ลบแค่รูป — แถวยังอยู่ (content_fingerprint ยังต้องใช้กันใบซ้ำ)"""
    rec, _ = _add(db_session, member_id, images, receipt_id="old", days_old=100)

    purge_old_images(db_session, images, retention_days=90, today=TODAY)

    db_session.refresh(rec)
    assert db_session.get(ReceiptRecord, rec.id) is not None
    assert rec.content_fingerprint == "fp-old", "ลายนิ้วมือกันซ้ำต้องยังอยู่"


def test_idempotent_second_run_deletes_nothing(db_session, member_id, images):
    """★ รันซ้ำต้องไม่หยิบแถวเดิมมาลบอีก (ทำเครื่องหมายแล้ว)"""
    _add(db_session, member_id, images, receipt_id="old", days_old=100)

    first = purge_old_images(db_session, images, retention_days=90, today=TODAY)
    second = purge_old_images(db_session, images, retention_days=90, today=TODAY)

    assert first.images_deleted == 1
    assert second.images_deleted == 0
    assert second.already_gone == 0, "แถวที่ลบรูปแล้วต้องไม่ถูกหยิบมาอีก"


def test_missing_file_does_not_crash(db_session, member_id, images):
    """ไฟล์ถูกลบด้วยมือไปก่อน → นับเป็น already_gone ไม่ error"""
    rec, key = _add(db_session, member_id, images, receipt_id="old", days_old=100)
    images._storage.delete(key)  # ลบไฟล์ทิ้งก่อน

    result = purge_old_images(db_session, images, retention_days=90, today=TODAY)

    assert result.images_deleted == 0
    assert result.already_gone == 1
    db_session.refresh(rec)
    assert rec.source_image_id == "", "ต้องทำเครื่องหมายว่าจัดการแล้ว แม้ไฟล์หาย"


def test_nothing_old_enough(db_session, member_id, images):
    _add(db_session, member_id, images, receipt_id="new", days_old=10)
    result = purge_old_images(db_session, images, retention_days=90, today=TODAY)
    assert result.images_deleted == 0
