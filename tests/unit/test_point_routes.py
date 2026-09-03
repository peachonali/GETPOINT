"""เทส GET /points/me — ดูแต้มสะสม + ประวัติของตัวเอง"""
import pytest
from fastapi.testclient import TestClient

from app.database.db import get_session
from app.database.members import Member
from app.database.receipts import STATUS_AWARDED, STATUS_FAILED, ReceiptRecord
from app.database.tenants import Tenant
from app.external.crm_interface import CrmCustomer, CrmPort, PointAwardResult
from app.main import app
from app.routes.auth_routes import require_line_user
from app.routes.dependencies import get_crm, get_tenant_id

TENANT = "v-club"
LINE_USER = "U-line-1"
PHONE = "0812345678"
HEADER = {"Authorization": "Bearer good"}


class _FakeCrm(CrmPort):
    def __init__(self, balance=250, boom=False):
        self.balance = balance
        self.boom = boom

    def find_customer(self, phone):
        if self.boom:
            from app.reliability.errors import ExternalServiceError
            raise ExternalServiceError("crm", "ล่ม", retryable=True)
        return CrmCustomer(customer_id="C1", phone=phone, points_balance=self.balance)

    def register_customer(self, phone, name=None): return CrmCustomer("C1", phone)
    def add_points(self, **k): return PointAwardResult(reference=k["reference"])


@pytest.fixture
def ctx(db_session):
    db_session.add(Tenant(id=TENANT, name="V-CLUB"))
    member = Member(
        tenant_id=TENANT, line_user_id=LINE_USER, phone=PHONE,
        phone_verified=True, crm_customer_id="C1",
    )
    db_session.add(member)
    db_session.commit()

    crm = _FakeCrm()
    app.dependency_overrides[require_line_user] = lambda: LINE_USER
    app.dependency_overrides[get_tenant_id] = lambda: TENANT
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_crm] = lambda: crm

    yield {"client": TestClient(app), "session": db_session, "member": member, "crm": crm}
    app.dependency_overrides.clear()


def _add_receipt(session, member_id, *, amount, points, status=STATUS_AWARDED, ref="r"):
    session.add(ReceiptRecord(
        tenant_id=TENANT, member_id=member_id,
        content_fingerprint=f"fp-{ref}", image_fingerprint="img",
        merchant="KFC", total_amount=amount, reference_codes=[],
        status=status, points_awarded=points, crm_reference=ref, source_image_id="img",
    ))
    session.commit()


def test_shows_balance_and_history(ctx):
    _add_receipt(ctx["session"], ctx["member"].id, amount=149.0, points=1, ref="a")

    body = ctx["client"].get("/points/me", headers=HEADER).json()

    assert body["points_balance"] == 250        # จาก CRM
    assert len(body["history"]) == 1
    assert body["history"][0]["amount"] == 149.0
    assert body["history"][0]["points"] == 1


def test_history_only_awarded(ctx):
    """ประวัติแสดงเฉพาะใบที่ได้แต้มแล้ว — ใบที่ยังค้างไม่โผล่"""
    _add_receipt(ctx["session"], ctx["member"].id, amount=100.0, points=1, ref="ok")
    _add_receipt(ctx["session"], ctx["member"].id, amount=200.0, points=2,
                 status=STATUS_FAILED, ref="failed")

    body = ctx["client"].get("/points/me", headers=HEADER).json()
    assert len(body["history"]) == 1
    assert body["history"][0]["amount"] == 100.0


def test_history_only_own_receipts(ctx):
    """★ เห็นเฉพาะใบของตัวเอง — ไม่เห็นของคนอื่น"""
    other = Member(tenant_id=TENANT, line_user_id="U2", phone="0899999999", crm_customer_id="C2")
    ctx["session"].add(other)
    ctx["session"].commit()
    _add_receipt(ctx["session"], ctx["member"].id, amount=100.0, points=1, ref="mine")
    _add_receipt(ctx["session"], other.id, amount=999.0, points=9, ref="theirs")

    body = ctx["client"].get("/points/me", headers=HEADER).json()
    assert len(body["history"]) == 1
    assert body["history"][0]["amount"] == 100.0


def test_balance_none_when_crm_down_but_history_still_shows(ctx):
    """★ CRM ล่ม → แต้มสะสมเป็น None แต่ประวัติยังแสดงได้ (ไม่พังทั้งหน้า)"""
    ctx["crm"].boom = True
    _add_receipt(ctx["session"], ctx["member"].id, amount=100.0, points=1, ref="a")

    body = ctx["client"].get("/points/me", headers=HEADER).json()
    assert body["points_balance"] is None
    assert len(body["history"]) == 1


def test_unverified_member_cannot_see_points(ctx):
    """ยังไม่ผูก CRM = ยังไม่มีแต้มให้ดู → บอกให้ยืนยันเบอร์ก่อน"""
    ctx["member"].crm_customer_id = None
    ctx["session"].commit()

    resp = ctx["client"].get("/points/me", headers=HEADER)
    assert resp.status_code == 400
    assert "ยืนยันเบอร์" in resp.json()["error"]
