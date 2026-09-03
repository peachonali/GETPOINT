"""เทส app/external/loga_client.py

ใช้ LogaTokenProvider ตัวจริงคู่กับ loga ปลอม (MockTransport) — ไม่ใช้ provider ปลอม
เพราะอยากเทส "การต่อกันของสองไฟล์" ด้วย โดยเฉพาะเส้นทาง login ใหม่เมื่อ token ถูกปฏิเสธ
"""
import httpx
import pytest

from app.external.crm_interface import CrmPort
from app.external.loga_client import LogaClient
from app.external.loga_token import LogaTokenProvider
from app.reliability.errors import CrmCallError

BASE_URL = "https://loga.example"
CARD_ID = "1"
DEVICE_ID = "getpoint-test-01"
LOGIN_PATH = "/api/main/login"

PHONE = "0812345678"


def _ok(data: dict) -> httpx.Response:
    return httpx.Response(200, json={"code": 200, "msg": "success", "data": data})


def _rejected(code: int = 400, msg: str = "rejected") -> httpx.Response:
    return httpx.Response(200, json={"code": code, "msg": msg})


def _login_ok(token: str = "TOKEN-1") -> httpx.Response:
    return _ok({"token": token, "store_id": "s1"})


def _client(handler) -> LogaClient:
    """ประกอบ LogaClient + LogaTokenProvider ที่คุยกับ loga ปลอมตัวเดียวกัน"""
    http = httpx.Client(transport=httpx.MockTransport(handler))
    tokens = LogaTokenProvider(
        base_url=BASE_URL, user="u", password="p", device_id=DEVICE_ID, http_client=http
    )
    return LogaClient(
        base_url=BASE_URL,
        card_id=CARD_ID,
        device_id=DEVICE_ID,
        token_provider=tokens,
        http_client=http,
    )


def _serving(response: httpx.Response, captured: list | None = None):
    """handler ที่ตอบ login ให้อัตโนมัติ แล้วตอบ response เดิมกับทุก path ที่เหลือ"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == LOGIN_PATH:
            return _login_ok()
        if captured is not None:
            captured.append(request)
        return response

    return handler


# ═══════════════════════════════════════════
# สัญญา
# ═══════════════════════════════════════════

def test_loga_client_is_a_crm_port():
    """ถ้าไม่ implement ครบตามสัญญา Python จะสร้าง instance ไม่ได้เลย"""
    assert isinstance(_client(_serving(_ok({}))), CrmPort)


def test_no_logout_method_exists():
    """logout ฆ่า token ที่ทุก process ใช้อยู่ (ADR 0003 ข้อ 3)
    เทสนี้ทำให้ "ความตั้งใจที่จะไม่มี" กลายเป็นข้อบังคับที่ตรวจได้ ไม่ใช่แค่คอมเมนต์"""
    assert not hasattr(LogaClient, "logout")


# ═══════════════════════════════════════════
# ค่าบังคับที่ต้องติดไปทุกครั้ง
# ═══════════════════════════════════════════

def test_every_call_carries_token_device_id_and_card_id():
    """ลืมตัวใดตัวหนึ่ง = loga ปฏิเสธแบบงงๆ · เติมที่เดียวใน _send จึงลืมไม่ได้"""
    captured = []
    _client(_serving(_ok({"user_info": {"uid": 5}}), captured)).find_customer(PHONE)

    params = captured[0].url.params
    assert params["token"] == "TOKEN-1"
    assert params["uuid"] == DEVICE_ID
    assert params["card_id"] == CARD_ID


# ═══════════════════════════════════════════
# find_customer
# ═══════════════════════════════════════════

def test_find_customer_returns_customer_from_user_info():
    customer = _client(
        _serving(_ok({
            "user_info": {"uid": 5, "fname": "สมชาย", "lname": "ใจดี", "tel": PHONE},
            "point": {"now": 120},
        }))
    ).find_customer(PHONE)

    assert customer.customer_id == "5"
    assert customer.name == "สมชาย ใจดี"
    assert customer.points_balance == 120


def test_find_customer_also_reads_uid_from_card():
    """เอกสาร 2 ฉบับบอกตำแหน่ง uid ไม่ตรงกัน — ต้องอ่านได้ทั้งสองที่จนกว่าจะยิงจริง"""
    customer = _client(_serving(_ok({"card": {"uid": 7}}))).find_customer(PHONE)
    assert customer.customer_id == "7"


def test_find_customer_uses_p_prefix_for_plastic_card_member():
    """สมาชิกที่ระบบเราสมัครให้จะเป็นบัตรพลาสติก — ให้แต้มต้องใช้ 'P' + pcard_id"""
    customer = _client(_serving(_ok({"user_info": {"pcard_id": 42}}))).find_customer(PHONE)
    assert customer.customer_id == "P42"


def test_find_customer_prefers_uid_when_member_has_both():
    customer = _client(
        _serving(_ok({"user_info": {"uid": 5, "pcard_id": 42}}))
    ).find_customer(PHONE)
    assert customer.customer_id == "5"


def test_find_customer_handles_uid_zero():
    """uid = 0 ต้องถือว่า 'มีรหัส' — ถ้าใช้ `or` ธรรมดาจะกลายเป็นไม่พบสมาชิก"""
    customer = _client(_serving(_ok({"user_info": {"uid": 0}}))).find_customer(PHONE)
    assert customer.customer_id == "0"


def test_find_customer_returns_none_when_not_found():
    assert _client(_serving(_rejected(msg="not found"))).find_customer(PHONE) is None


def test_find_customer_sends_phone_as_cuid():
    captured = []
    _client(_serving(_ok({"user_info": {"uid": 1}}), captured)).find_customer(PHONE)
    assert captured[0].url.params["cuid"] == PHONE


# ═══════════════════════════════════════════
# register_customer
# ═══════════════════════════════════════════

def test_register_customer_returns_plastic_card_id():
    customer = _client(_serving(_ok({"pcard_id": 99}))).register_customer(PHONE, "สมหญิง")

    assert customer.customer_id == "P99"
    assert customer.phone == PHONE
    assert customer.name == "สมหญิง"


def test_register_customer_sends_phone_in_place_of_physical_card():
    """ร้านเราไม่มีบัตรพลาสติกจริง — loga อนุญาตให้ใช้เบอร์แทน serial/barcode"""
    captured = []
    _client(_serving(_ok({"pcard_id": 99}), captured)).register_customer(PHONE)

    params = captured[0].url.params
    assert params["mobile"] == PHONE
    assert params["serial"] == PHONE
    assert params["barcode"] == PHONE


def test_register_customer_raises_when_rejected():
    """เช่นเบอร์นี้มีสมาชิกอยู่แล้ว — loga ไม่ให้สมัครซ้ำ"""
    with pytest.raises(CrmCallError):
        _client(_serving(_rejected(msg="duplicate mobile"))).register_customer(PHONE)


def test_register_customer_raises_when_no_card_id_returned():
    with pytest.raises(CrmCallError):
        _client(_serving(_ok({}))).register_customer(PHONE)


# ═══════════════════════════════════════════
# add_points — หัวใจของระบบ
# ═══════════════════════════════════════════

def _add_points(client: LogaClient):
    return client.add_points(
        customer_id="5", cost=250.0, formula_id="7",
        remark="สะสมแต้มจากใบเสร็จ", reference="INV-001",
    )


def test_add_points_sends_cost_and_formula_but_never_point():
    """★ ถ้าเผลอส่ง point ไปด้วย loga จะใช้ point แล้วเก็บ cost เป็นข้อมูลประกอบ
    = กลายเป็นวิธีแบบ A โดยไม่ตั้งใจ ขัดกับ ADR 0002"""
    captured = []
    _add_points(_client(_serving(_ok({"point": {"now": 125}}), captured)))

    params = captured[0].url.params
    assert params["cost"] == "250.00"
    assert params["formula_id"] == "7"
    assert "point" not in params


def test_add_points_sends_reference_for_idempotency():
    """reference ซ้ำ = loga ถือเป็นรายการเดิม ไม่บันทึกซ้ำ (ADR 0003 ข้อ 7)"""
    captured = []
    _add_points(_client(_serving(_ok({"point": {"now": 125}}), captured)))

    assert captured[0].url.params["reference"] == "INV-001"
    assert captured[0].url.params["remark"] == "สะสมแต้มจากใบเสร็จ"


def test_add_points_returns_balance_but_not_points_added():
    """loga คืนแค่ยอดสะสมล่าสุด ไม่บอกว่ารายการนี้ได้กี่แต้ม"""
    result = _add_points(_client(_serving(_ok({"point": {"now": 125}}))))

    assert result.points_balance == 125
    assert result.points_added is None
    assert result.reference == "INV-001"


def test_add_points_raises_when_rejected():
    with pytest.raises(CrmCallError) as exc_info:
        _add_points(_client(_serving(_rejected(code=404, msg="customer not found"))))

    assert exc_info.value.retryable is False
    assert exc_info.value.code == 404


# ═══════════════════════════════════════════
# token ถูกปฏิเสธ → login ใหม่แล้วลองอีกครั้ง
# ═══════════════════════════════════════════

def test_rejected_token_triggers_relogin_and_retry():
    logins = []
    business_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == LOGIN_PATH:
            logins.append(request)
            return _login_ok(f"TOKEN-{len(logins)}")

        business_calls.append(request)
        if len(business_calls) == 1:
            return _rejected(code=401, msg="invalid token")  # ครั้งแรกโดนปฏิเสธ
        return _ok({"point": {"now": 125}})

    result = _add_points(_client(handler))

    assert len(logins) == 2, "ต้อง login ใหม่หลังโดนปฏิเสธ"
    assert len(business_calls) == 2, "ต้องลองยิงซ้ำหลัง login ใหม่"
    assert business_calls[1].url.params["token"] == "TOKEN-2", "ครั้งที่สองต้องใช้ token ใหม่"
    assert result.points_balance == 125


def test_relogin_happens_only_once_per_call():
    """กันวนไม่รู้จบ: ถ้า login ใหม่แล้วยังโดนปฏิเสธอีก ต้องยอมแพ้ ไม่ใช่ลองต่อเรื่อยๆ"""
    logins = []
    business_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == LOGIN_PATH:
            logins.append(request)
            return _login_ok(f"TOKEN-{len(logins)}")
        business_calls.append(request)
        return _rejected(code=401, msg="invalid token")

    with pytest.raises(CrmCallError):
        _add_points(_client(handler))

    assert len(business_calls) == 2, "ยิงแค่ 2 ครั้ง (ครั้งแรก + ลองใหม่หนึ่งครั้ง)"
