"""เทส app/send_queue/dead_letter.py — รายงาน + ปลุกใบที่ค้าง DEAD"""
import pytest

from app.database.members import Member
from app.database.receipts import (
    STATUS_AWARDED, STATUS_DEAD, STATUS_FAILED, ReceiptRecord,
)
from app.database.tenants import Tenant
from app.send_queue.dead_letter import list_dead, revive

TENANT = "v-club"


@pytest.fixture
def member_id(db_session) -> int:
    db_session.add(Tenant(id=TENANT, name="V-CLUB"))
    member = Member(tenant_id=TENANT, line_user_id="U1", crm_customer_id="C1")
    db_session.add(member)
    db_session.commit()
    return member.id


def _add(session, member_id, *, status, reference, attempts=0, tenant=TENANT):
    record = ReceiptRecord(
        tenant_id=tenant, member_id=member_id,
        content_fingerprint=f"fp-{reference}", image_fingerprint="img",
        merchant="ร้าน", total_amount=100.0, reference_codes=[],
        status=status, crm_reference=reference, send_attempts=attempts,
        source_image_id="img",
    )
    session.add(record)
    session.commit()
    return record


def test_lists_only_dead_receipts(db_session, member_id):
    _add(db_session, member_id, status=STATUS_DEAD, reference="d1")
    _add(db_session, member_id, status=STATUS_DEAD, reference="d2")
    _add(db_session, member_id, status=STATUS_FAILED, reference="f1")
    _add(db_session, member_id, status=STATUS_AWARDED, reference="a1")

    view = list_dead(db_session, TENANT)

    assert view.dead_count == 2
    assert view.still_retrying_count == 1   # ใบ FAILED ยังลองส่งซ้ำอยู่
    assert {r.crm_reference for r in view.records} == {"d1", "d2"}


def test_other_tenant_not_included(db_session, member_id):
    other = Member(tenant_id="other", line_user_id="U2", crm_customer_id="C2")
    db_session.add(Tenant(id="other", name="Other"))
    db_session.add(other)
    db_session.commit()
    _add(db_session, member_id, status=STATUS_DEAD, reference="mine")
    _add(db_session, other.id, status=STATUS_DEAD, reference="theirs", tenant="other")

    view = list_dead(db_session, TENANT)
    assert view.dead_count == 1
    assert view.records[0].crm_reference == "mine"


def test_revive_resets_to_failed(db_session, member_id):
    """★ ปลุกใบ DEAD กลับเข้าคิวส่งซ้ำ + รีเซ็ตตัวนับ (หลังคนแก้ต้นเหตุแล้ว)"""
    dead = _add(db_session, member_id, status=STATUS_DEAD, reference="d1", attempts=5)

    assert revive(db_session, dead.id) is True
    db_session.refresh(dead)
    assert dead.status == STATUS_FAILED
    assert dead.send_attempts == 0


def test_revive_refuses_non_dead(db_session, member_id):
    """★ ปลุกได้เฉพาะใบ DEAD — กันเผลอปลุกใบที่ได้แต้มไปแล้ว (จะให้แต้มซ้ำ)"""
    awarded = _add(db_session, member_id, status=STATUS_AWARDED, reference="a1")

    assert revive(db_session, awarded.id) is False
    db_session.refresh(awarded)
    assert awarded.status == STATUS_AWARDED


def test_revive_missing_receipt(db_session, member_id):
    assert revive(db_session, 99999) is False


def test_empty(db_session, member_id):
    view = list_dead(db_session, TENANT)
    assert view.dead_count == 0
    assert view.records == []