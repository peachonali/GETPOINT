"""เทส app/send_queue/send_queue.py — ส่งแต้มที่ค้าง (FAILED) เข้า CRM ใหม่"""
import pytest

from app.database.members import Member
from app.database.receipts import (
    STATUS_AWARDED, STATUS_DEAD, STATUS_FAILED, STATUS_PENDING, ReceiptRecord,
)
from app.database.tenants import Tenant
from app.external.crm_interface import CrmCustomer, CrmPort, PointAwardResult
from app.reliability.errors import CrmCallError, ExternalServiceError
from app.send_queue.send_queue import _MAX_SEND_ATTEMPTS, PointResender

TENANT = "v-club"
FORMULA = "7"


class _FakeCrm(CrmPort):
    def __init__(self):
        self.awards: list[str] = []       # reference ที่ส่งสำเร็จ
        self.calls = 0                    # จำนวนครั้งที่ถูกเรียก (รวมที่ล้ม)
        self.fail_all = False             # ล้มทุกใบแบบ "ระบบล่ม" (retryable → หยุด batch)
        self.fail_refs: set[str] = set()  # ล้มเฉพาะ reference เหล่านี้แบบ "ระบบล่ม"
        self.reject_refs: set[str] = set()  # loga ปฏิเสธเฉพาะใบ (ไม่ retryable → นับ/dead)

    def find_customer(self, phone): return None
    def register_customer(self, phone, name=None): return CrmCustomer("C1", phone)

    def add_points(self, *, customer_id, cost, formula_id, remark, reference):
        self.calls += 1
        if reference in self.reject_refs:
            raise CrmCallError("loga ปฏิเสธใบนี้")  # retryable=False
        if self.fail_all or reference in self.fail_refs:
            raise ExternalServiceError("crm", "ล่ม", retryable=True)
        self.awards.append(reference)
        return PointAwardResult(reference=reference, points_balance=100)


@pytest.fixture
def member_id(db_session) -> int:
    db_session.add(Tenant(id=TENANT, name="V-CLUB"))
    member = Member(tenant_id=TENANT, line_user_id="U1", crm_customer_id="CUST-1")
    db_session.add(member)
    db_session.commit()
    return member.id


def _add(session, member_id, *, amount, status, reference):
    record = ReceiptRecord(
        tenant_id=TENANT, member_id=member_id,
        content_fingerprint=f"fp-{reference}", image_fingerprint="img",
        merchant="ร้านทดสอบ", total_amount=amount, reference_codes=[],
        status=status, crm_reference=reference, source_image_id="img",
    )
    session.add(record)
    session.commit()
    return record


def test_resends_failed_receipt(db_session, member_id):
    """★ ใบ FAILED ถูกส่งซ้ำสำเร็จ → กลายเป็น AWARDED"""
    record = _add(db_session, member_id, amount=100.0, status=STATUS_FAILED, reference="gp1")
    crm = _FakeCrm()

    summary = PointResender(crm, formula_id=FORMULA).run(db_session)

    assert summary.succeeded == 1
    assert crm.awards == ["gp1"]
    db_session.refresh(record)
    assert record.status == STATUS_AWARDED
    assert record.points_awarded == 1


def test_resend_uses_same_reference(db_session, member_id):
    """★ ต้องส่งด้วย reference เดิม — ยิงซ้ำ loga จะไม่ให้แต้มซ้ำ (idempotent)"""
    _add(db_session, member_id, amount=100.0, status=STATUS_FAILED, reference="gp-keep")
    crm = _FakeCrm()

    PointResender(crm, formula_id=FORMULA).run(db_session)
    assert crm.awards == ["gp-keep"]


def test_only_failed_receipts_are_resent(db_session, member_id):
    """ใบ AWARDED/PENDING ต้องไม่ถูกส่งซ้ำ"""
    _add(db_session, member_id, amount=100.0, status=STATUS_FAILED, reference="f")
    _add(db_session, member_id, amount=200.0, status=STATUS_AWARDED, reference="a")
    _add(db_session, member_id, amount=300.0, status=STATUS_PENDING, reference="p")
    crm = _FakeCrm()

    PointResender(crm, formula_id=FORMULA).run(db_session)
    assert crm.awards == ["f"]


def test_stops_batch_when_crm_still_down(db_session, member_id):
    """★ loga ยังล่ม → หยุดทั้ง batch ทันที ไม่ลองใบที่เหลือเปล่าประโยชน์"""
    _add(db_session, member_id, amount=100.0, status=STATUS_FAILED, reference="f1")
    _add(db_session, member_id, amount=200.0, status=STATUS_FAILED, reference="f2")
    _add(db_session, member_id, amount=300.0, status=STATUS_FAILED, reference="f3")
    crm = _FakeCrm()
    crm.fail_all = True

    summary = PointResender(crm, formula_id=FORMULA).run(db_session)

    assert summary.succeeded == 0
    assert summary.still_failing == 3
    assert crm.calls == 1, "ต้องหยุดหลังใบแรกล้ม ไม่ลองใบที่ 2, 3"


def test_partial_success_then_stop(db_session, member_id):
    """สำเร็จ 2 ใบแรก แล้ว loga ล่มใบที่ 3 → 2 สำเร็จ เหลือค้างต่อ"""
    _add(db_session, member_id, amount=100.0, status=STATUS_FAILED, reference="f1")
    _add(db_session, member_id, amount=200.0, status=STATUS_FAILED, reference="f2")
    _add(db_session, member_id, amount=300.0, status=STATUS_FAILED, reference="f3")
    crm = _FakeCrm()
    crm.fail_refs = {"f3"}  # ใบ 3 ล้ม ที่เหลือผ่าน

    summary = PointResender(crm, formula_id=FORMULA).run(db_session)
    assert summary.succeeded == 2
    assert summary.still_failing == 1


def test_skips_member_without_crm_link(db_session, member_id):
    """สมาชิกที่ยังผูก CRM ไม่สำเร็จ → ข้าม ไม่ใช่หน้าที่ resend แก้"""
    orphan = Member(tenant_id=TENANT, line_user_id="U2", crm_customer_id=None)
    db_session.add(orphan)
    db_session.commit()
    _add(db_session, orphan.id, amount=100.0, status=STATUS_FAILED, reference="orphan")
    crm = _FakeCrm()

    summary = PointResender(crm, formula_id=FORMULA).run(db_session)
    assert crm.awards == []
    assert summary.succeeded == 0


def test_nothing_to_resend(db_session, member_id):
    summary = PointResender(_FakeCrm(), formula_id=FORMULA).run(db_session)
    assert summary.attempted == 0 and summary.succeeded == 0


# ═══════════════════════════════════════════
# ★ dead letter — loga ปฏิเสธเฉพาะใบ (ไม่ใช่ระบบล่ม)
# ═══════════════════════════════════════════

def test_rejected_receipt_counts_attempt_and_continues(db_session, member_id):
    """★ loga ปฏิเสธใบแรกเฉพาะใบ → นับ attempt แล้วไปใบถัดไป (ไม่หยุดทั้ง batch)

    ต่างจาก "ระบบล่ม" ที่หยุด batch — ใบพังใบเดียวต้องไม่บล็อกใบอื่น
    """
    bad = _add(db_session, member_id, amount=100.0, status=STATUS_FAILED, reference="bad")
    _add(db_session, member_id, amount=200.0, status=STATUS_FAILED, reference="good")
    crm = _FakeCrm()
    crm.reject_refs = {"bad"}

    summary = PointResender(crm, formula_id=FORMULA).run(db_session)

    assert summary.succeeded == 1          # ใบ good ผ่าน
    assert crm.awards == ["good"]
    db_session.refresh(bad)
    assert bad.send_attempts == 1          # ใบ bad ถูกนับ
    assert bad.status == STATUS_FAILED     # ยังไม่ dead (ยังไม่ครบเกณฑ์)


def test_receipt_moves_to_dead_after_max_attempts(db_session, member_id):
    """★★ ใบที่ loga ปฏิเสธซ้ำจนครบเกณฑ์ → ย้ายไป DEAD ไม่ลองอีก

    กันใบพังใบเดียวบล็อกคิวไปตลอดกาล (มันเป็นใบเก่าสุดที่ล้มก่อนเสมอ)
    """
    bad = _add(db_session, member_id, amount=100.0, status=STATUS_FAILED, reference="bad")
    bad.send_attempts = _MAX_SEND_ATTEMPTS - 1  # ใกล้ครบแล้ว
    db_session.commit()
    crm = _FakeCrm()
    crm.reject_refs = {"bad"}

    summary = PointResender(crm, formula_id=FORMULA).run(db_session)

    assert summary.dead_lettered == 1
    db_session.refresh(bad)
    assert bad.status == STATUS_DEAD
    assert bad.send_attempts == _MAX_SEND_ATTEMPTS


def test_dead_receipt_not_picked_up_again(db_session, member_id):
    """ใบที่ DEAD แล้วต้องไม่ถูกส่งซ้ำอีก (หลุดจากคิว FAILED)"""
    _add(db_session, member_id, amount=100.0, status=STATUS_DEAD, reference="dead")
    crm = _FakeCrm()

    summary = PointResender(crm, formula_id=FORMULA).run(db_session)
    assert summary.attempted == 0
    assert crm.calls == 0


def test_system_outage_does_not_dead_letter(db_session, member_id):
    """★ ระบบล่ม (retryable) ต้องไม่นับ attempt/ไม่ dead — ไม่ใช่ความผิดของใบ

    ไม่งั้นใบสุจริตจะถูกฆ่าทิ้งเพราะ loga บังเอิญล่มตอนนั้น
    """
    r = _add(db_session, member_id, amount=100.0, status=STATUS_FAILED, reference="f1")
    crm = _FakeCrm()
    crm.fail_all = True  # ระบบล่ม

    PointResender(crm, formula_id=FORMULA).run(db_session)

    db_session.refresh(r)
    assert r.send_attempts == 0
    assert r.status == STATUS_FAILED
