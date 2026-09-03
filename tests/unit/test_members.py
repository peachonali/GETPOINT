"""เทส model tenants + members (app/database/)

เทสผ่าน db_session (SQLite in-memory) — พิสูจน์ว่าสคีมาถูก + constraint บังคับจริง
constraint ที่ไม่ถูกเทส = constraint ที่พังเงียบตอน migrate ไป Postgres
"""
from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.database.members import Member
from app.database.tenants import Tenant


def _member(**overrides) -> Member:
    base = dict(tenant_id="v-club", line_user_id="U-line-1")
    base.update(overrides)
    return Member(**base)


# ═══════════════════════════════════════════
# tenants
# ═══════════════════════════════════════════

def test_create_and_read_tenant(db_session):
    db_session.add(Tenant(id="v-club", name="V-CLUB"))
    db_session.commit()

    found = db_session.get(Tenant, "v-club")
    assert found.name == "V-CLUB"
    assert isinstance(found.created_at, datetime), "created_at ต้องเติมเองจาก server_default"


# ═══════════════════════════════════════════
# members — ค่าเริ่มต้นสะท้อน UX แบบผสม
# ═══════════════════════════════════════════

def test_new_member_starts_unverified_without_phone(db_session):
    """คนเพิ่งแอด LINE: มี record ได้ แต่ยังไม่มีเบอร์ + ยังไม่ verify
    (UX แบบผสม — เห็นหน้าสแกนก่อน กั้น OTP ตอนรับแต้มครั้งแรก)"""
    member = _member()
    db_session.add(member)
    db_session.commit()

    assert member.id is not None
    assert member.phone is None
    assert member.crm_customer_id is None
    assert member.phone_verified is False
    assert isinstance(member.created_at, datetime)


def test_member_lifecycle_fields_fill_in(db_session):
    """เดินครบเส้น: verify OTP → เติมเบอร์ → ผูก loga → เติม crm_customer_id"""
    member = _member()
    db_session.add(member)
    db_session.commit()

    member.phone = "0812345678"
    member.phone_verified = True
    member.crm_customer_id = "P42"
    db_session.commit()

    reloaded = db_session.get(Member, member.id)
    assert reloaded.phone == "0812345678"
    assert reloaded.phone_verified is True
    assert reloaded.crm_customer_id == "P42"


# ═══════════════════════════════════════════
# constraint — 1 LINE user = 1 สมาชิก ต่อ 1 แบรนด์
# ═══════════════════════════════════════════

def test_same_line_user_cannot_duplicate_within_tenant(db_session):
    db_session.add(_member(line_user_id="U-dup"))
    db_session.commit()

    db_session.add(_member(line_user_id="U-dup"))  # แอดใหม่/กดซ้ำ → line_user_id เดิม
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_same_line_user_id_allowed_across_different_tenants(db_session):
    """คนละแบรนด์เก็บแยกกัน — line_user_id เดียวกันในต่าง tenant ไม่ชนกัน
    (unique เป็น (tenant_id, line_user_id) ไม่ใช่ line_user_id เดี่ยว)"""
    db_session.add(_member(tenant_id="v-club", line_user_id="U-same"))
    db_session.add(_member(tenant_id="other-brand", line_user_id="U-same"))
    db_session.commit()  # ต้องไม่ error

    assert db_session.query(Member).count() == 2


def test_multiple_unverified_members_can_have_null_phone(db_session):
    """หลายคนที่ยังไม่ verify (phone = None) ต้องอยู่ร่วมกันได้
    (ยืนยันว่าไม่ได้เผลอใส่ unique constraint บน phone ที่จะสะดุด null)"""
    db_session.add(_member(line_user_id="U-1"))
    db_session.add(_member(line_user_id="U-2"))
    db_session.commit()

    assert db_session.query(Member).filter(Member.phone.is_(None)).count() == 2
