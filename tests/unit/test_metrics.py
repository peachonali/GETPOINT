"""เทส app/observability/metrics.py — สรุปสุขภาพระบบจากตาราง receipts"""
from datetime import date, datetime, timedelta

import pytest

from app.database.members import Member
from app.database.receipts import (
    STATUS_AWARDED, STATUS_DEAD, STATUS_FAILED, STATUS_PENDING, STATUS_REJECTED, ReceiptRecord,
)
from app.database.tenants import Tenant
from app.observability.metrics import scan_metrics

TENANT = "v-club"
TODAY = date(2026, 6, 30)


@pytest.fixture
def member_id(db_session) -> int:
    db_session.add(Tenant(id=TENANT, name="V-CLUB"))
    m = Member(tenant_id=TENANT, line_user_id="U1", crm_customer_id="C1")
    db_session.add(m)
    db_session.commit()
    return m.id


def _add(session, member_id, *, status, days_old=1, tenant=TENANT, n=1):
    for i in range(n):
        session.add(ReceiptRecord(
            tenant_id=tenant, member_id=member_id,
            content_fingerprint=f"fp-{status}-{days_old}-{i}", image_fingerprint="img",
            merchant="ร้าน", total_amount=100.0, reference_codes=[], status=status,
            source_image_id="img",
            created_at=datetime.combine(TODAY - timedelta(days=days_old), datetime.min.time()),
        ))
    session.commit()


def test_counts_by_status(db_session, member_id):
    _add(db_session, member_id, status=STATUS_AWARDED, n=8)
    _add(db_session, member_id, status=STATUS_FAILED, n=2)
    _add(db_session, member_id, status=STATUS_DEAD, n=1)
    _add(db_session, member_id, status=STATUS_REJECTED, n=3)
    _add(db_session, member_id, status=STATUS_PENDING, n=1)

    m = scan_metrics(db_session, TENANT, since_days=7, today=TODAY)

    assert m.awarded == 8
    assert m.failed == 2
    assert m.dead == 1
    assert m.rejected == 3
    assert m.pending == 1
    assert m.total == 15


def test_award_rate_excludes_rejected(db_session, member_id):
    """★ อัตราสำเร็จคิดจากใบที่ "ควรได้แต้ม" — ใบซ้ำที่ถูกปฏิเสธไม่ใช่ความล้มเหลว"""
    _add(db_session, member_id, status=STATUS_AWARDED, n=9)
    _add(db_session, member_id, status=STATUS_FAILED, n=1)
    _add(db_session, member_id, status=STATUS_REJECTED, n=100)  # ใบซ้ำเยอะ ต้องไม่ฉุดอัตรา

    m = scan_metrics(db_session, TENANT, since_days=7, today=TODAY)
    assert m.award_rate == 0.9


def test_needs_attention_when_dead_exists(db_session, member_id):
    """★ มีใบ DEAD ค้าง = ต้องมีคนเข้าไปกู้ → ต้องเห็นง่าย"""
    _add(db_session, member_id, status=STATUS_AWARDED, n=5)
    assert not scan_metrics(db_session, TENANT, today=TODAY).needs_attention

    _add(db_session, member_id, status=STATUS_DEAD, n=1)
    assert scan_metrics(db_session, TENANT, today=TODAY).needs_attention


def test_only_within_window(db_session, member_id):
    """นับเฉพาะในช่วงเวลาที่ถาม — ใบเก่ากว่านั้นไม่นับ"""
    _add(db_session, member_id, status=STATUS_AWARDED, days_old=2, n=3)
    _add(db_session, member_id, status=STATUS_AWARDED, days_old=30, n=5)

    m = scan_metrics(db_session, TENANT, since_days=7, today=TODAY)
    assert m.awarded == 3


def test_other_tenant_not_counted(db_session, member_id):
    other = Member(tenant_id="other", line_user_id="U2", crm_customer_id="C2")
    db_session.add(Tenant(id="other", name="Other"))
    db_session.add(other)
    db_session.commit()
    _add(db_session, member_id, status=STATUS_AWARDED, n=2)
    _add(db_session, other.id, status=STATUS_AWARDED, tenant="other", n=9)

    assert scan_metrics(db_session, TENANT, today=TODAY).awarded == 2


def test_empty_award_rate_is_zero(db_session, member_id):
    """ไม่มีใบเลย → อัตรา 0 ไม่ใช่หารด้วยศูนย์"""
    assert scan_metrics(db_session, TENANT, today=TODAY).award_rate == 0.0
