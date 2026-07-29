"""เทส app/member/member_link.py (★ หัวใจ Step 2)

ใช้ FakeLoga (บังคับกฎเบอร์ซ้ำจริงเหมือน loga) + db_session (SQLite)
เทสเน้นเคส race เบอร์ซ้ำ — เคสที่พังเงียบแล้วลูกค้าผูกไม่ได้โดยไม่รู้สาเหตุ
"""
import pytest

from app.database.members import Member
from app.external.crm_interface import CrmCustomer
from app.external.fake_loga import FakeLoga
from app.member.member_link import MemberLinker
from app.reliability.errors import CrmCallError, InputValidationError

PHONE = "0812345678"


def _member(session, *, phone=PHONE, line_user_id="U-1") -> Member:
    member = Member(tenant_id="v-club", line_user_id=line_user_id, phone=phone)
    session.add(member)
    session.commit()
    return member


# ═══════════════════════════════════════════
# เส้นทางหลัก: มี/ไม่มีใน CRM
# ═══════════════════════════════════════════

def test_registers_new_customer_when_not_in_crm(db_session):
    fake = FakeLoga()
    member = _member(db_session)

    MemberLinker(fake).link(db_session, member)

    assert member.crm_customer_id is not None
    assert member.crm_customer_id.startswith("P")  # สมาชิกใหม่ = บัตรพลาสติก
    assert fake.find_customer(PHONE) is not None


def test_uses_existing_customer_when_already_in_crm(db_session):
    """ลูกค้าเคยเป็นสมาชิก loga อยู่แล้ว — ต้องใช้ id เดิม ไม่สมัครซ้ำ"""
    fake = FakeLoga()
    fake.seed_customer(PHONE, customer_id="U-existing-99")
    member = _member(db_session)

    MemberLinker(fake).link(db_session, member)

    assert member.crm_customer_id == "U-existing-99"
    assert len(fake.registered) == 0, "ห้ามสมัครใหม่เมื่อมีอยู่แล้ว"


# ═══════════════════════════════════════════
# race: เบอร์ซ้ำระหว่าง find กับ register
# ═══════════════════════════════════════════

class _RacyLoga(FakeLoga):
    """จำลอง race — ตอนเรา find ไม่เจอ แต่พอจะ register มีคนอื่นชิงสมัครไปแล้ว"""

    def register_customer(self, phone: str, name=None) -> CrmCustomer:
        # แอบใส่สมาชิกเข้าไปก่อน แล้วโยน error เบอร์ซ้ำเหมือน loga จริง
        self.seed_customer(phone, customer_id="U-raced-1")
        raise CrmCallError(f"เบอร์ {phone} มีสมาชิกอยู่แล้ว")


def test_recovers_from_duplicate_phone_race(db_session):
    """register โดนปฏิเสธเพราะเบอร์ซ้ำ → find อีกรอบ เอาตัวที่มีอยู่ (ไม่พังทั้งการผูก)"""
    member = _member(db_session)

    MemberLinker(_RacyLoga()).link(db_session, member)

    assert member.crm_customer_id == "U-raced-1"


class _BrokenLoga(FakeLoga):
    """register พังด้วยเหตุอื่นที่ไม่ใช่เบอร์ซ้ำ (เช่น card_id ผิด) — กู้ไม่ได้"""

    def register_customer(self, phone: str, name=None) -> CrmCustomer:
        raise CrmCallError("card_id ไม่ถูกต้อง")


def test_non_duplicate_registration_error_propagates(db_session):
    """ถ้า register พังเพราะเหตุอื่น (ไม่ใช่เบอร์ซ้ำ) ต้องโยนต่อ ไม่กลืนเงียบ
    ไม่งั้นจะได้ member ที่ crm_customer_id ว่างโดยไม่มีใครรู้ว่าพัง"""
    member = _member(db_session)

    with pytest.raises(CrmCallError):
        MemberLinker(_BrokenLoga()).link(db_session, member)

    assert member.crm_customer_id is None


# ═══════════════════════════════════════════
# idempotent + guard
# ═══════════════════════════════════════════

def test_link_is_idempotent(db_session):
    """ผูกแล้วเรียกซ้ำต้องไม่ยิง CRM อีก (เผื่อ retry หลัง CRM ล่ม)"""
    fake = FakeLoga()
    member = _member(db_session)

    MemberLinker(fake).link(db_session, member)
    first_id = member.crm_customer_id

    MemberLinker(fake).link(db_session, member)  # เรียกซ้ำ
    assert member.crm_customer_id == first_id
    assert len(fake.registered) == 1, "ครั้งที่สองต้องไม่สมัครใหม่"


def test_link_without_verified_phone_is_rejected(db_session):
    member = Member(tenant_id="v-club", line_user_id="U-2", phone=None)
    db_session.add(member)
    db_session.commit()

    with pytest.raises(InputValidationError):
        MemberLinker(FakeLoga()).link(db_session, member)
