"""เทส app/external/fake_loga.py

fake ถูกใช้เป็นฐานของเทสอื่นเกือบทั้งระบบ — ถ้า fake มีพฤติกรรมผิด เทสที่พึ่งมัน
จะเขียวแบบผิดๆ โดยไม่มีใครรู้ เทสชุดนี้จึงตรึงว่า fake บังคับกฎเดียวกับ loga จริง
"""
import pytest

from app.external.crm_interface import CrmCustomer, CrmPort
from app.external.fake_loga import FakeLoga
from app.reliability.errors import CrmCallError

PHONE = "0812345678"


def test_fake_is_a_crm_port():
    assert isinstance(FakeLoga(), CrmPort)


# ═══════════════════════════════════════════
# find / register
# ═══════════════════════════════════════════

def test_find_returns_none_when_unknown():
    assert FakeLoga().find_customer(PHONE) is None


def test_register_then_find():
    fake = FakeLoga()
    created = fake.register_customer(PHONE, "สมชาย")

    assert created.customer_id.startswith("P")  # สมาชิกที่ร้านสมัครให้ = บัตรพลาสติก
    assert fake.find_customer(PHONE) == created


def test_register_duplicate_phone_is_rejected():
    """กฎ loga ข้อ 6 — ถ้า fake ยอมให้ซ้ำ เทส member_link จะพลาดเคสสำคัญที่สุด"""
    fake = FakeLoga()
    fake.register_customer(PHONE)

    with pytest.raises(CrmCallError):
        fake.register_customer(PHONE)


def test_seed_customer_simulates_pre_existing_member():
    fake = FakeLoga()
    fake.seed_customer(PHONE, name="เจ้าเก่า", points=500)

    found = fake.find_customer(PHONE)
    assert found.name == "เจ้าเก่า"
    assert found.points_balance == 500


# ═══════════════════════════════════════════
# add_points
# ═══════════════════════════════════════════

def test_add_points_increases_balance():
    fake = FakeLoga()
    member = fake.seed_customer(PHONE, points=10)

    result = fake.add_points(
        customer_id=member.customer_id, cost=250.0, formula_id="7",
        remark="x", reference="INV-1",
    )

    assert result.points_balance == 20  # 10 เดิม + floor(250/25)=10
    assert result.points_added is None   # ตรงกับ loga จริง: คืนแค่ยอดรวม
    assert fake.find_customer(PHONE).points_balance == 20


def test_duplicate_reference_does_not_award_twice():
    """กฎ loga ข้อ 7 — reference ซ้ำ = รายการเดิม · นี่คือ idempotency ที่กันแต้มซ้ำ"""
    fake = FakeLoga()
    member = fake.seed_customer(PHONE, points=0)

    first = fake.add_points(customer_id=member.customer_id, cost=250.0,
                            formula_id="7", remark="x", reference="INV-1")
    second = fake.add_points(customer_id=member.customer_id, cost=250.0,
                             formula_id="7", remark="x", reference="INV-1")

    assert first.points_balance == second.points_balance == 10
    assert fake.find_customer(PHONE).points_balance == 10, "ยอดต้องไม่ขยับรอบสอง"
    assert len(fake.awards) == 1, "spy ต้องเห็นการให้แต้มจริงแค่ครั้งเดียว"


def test_add_points_to_unknown_customer_raises():
    with pytest.raises(CrmCallError):
        FakeLoga().add_points(customer_id="P999", cost=100.0,
                              formula_id="7", remark="x", reference="INV-1")


# ═══════════════════════════════════════════
# spy — ให้เทส e2e ตรวจว่ามีการเรียกจริงด้วยค่าที่ถูก
# ═══════════════════════════════════════════

def test_spy_records_registrations_and_awards():
    fake = FakeLoga()
    member = fake.register_customer(PHONE)
    fake.add_points(customer_id=member.customer_id, cost=250.0,
                    formula_id="7", remark="x", reference="INV-1")

    assert [c.phone for c in fake.registered] == [PHONE]
    assert [a.reference for a in fake.awards] == ["INV-1"]
