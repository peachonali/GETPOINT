"""เทส app/points/point_rate.py — อัตราแปลงยอดเงินเป็นแต้ม

อัตราที่ตกลงไว้: 100 บาท = 1 แต้ม (user ระบุ "เอาแบบนี้ไปก่อน ค่อยมาปรับเปลี่ยน")
"""
import pytest

from app.points.point_rate import BAHT_PER_POINT, points_for


def test_agreed_rate_is_one_hundred_baht_per_point():
    """★ ตรึงอัตราที่ตกลงกันไว้ — เปลี่ยนค่านี้ต้องตั้งใจ ไม่ใช่เผลอแก้"""
    assert BAHT_PER_POINT == 100


@pytest.mark.parametrize(
    "amount, expected",
    [
        (100, 1),
        (250, 2),
        (1000, 10),
        (2696, 26),      # ใบ The Pizza Company ในชุดทดสอบ
        (149, 1),        # ใบ KFC ในชุดทดสอบ
    ],
)
def test_points_for_amount(amount, expected):
    assert points_for(amount) == expected


def test_rounds_down_never_up():
    """★ ปัดลงเสมอ — ให้แต้มเกินคือความเสียหายที่ดึงคืนยาก

    199 บาท ต้องได้ 1 แต้ม ไม่ใช่ 2 (แม้จะ "เกือบ" 200)
    """
    assert points_for(199) == 1
    assert points_for(199.99) == 1
    assert points_for(99.99) == 0


def test_below_rate_earns_nothing():
    """ซื้อไม่ถึง 100 บาท = ยังไม่ได้แต้ม (ไม่ใช่ปัดขึ้นเป็น 1)"""
    assert points_for(1) == 0
    assert points_for(99) == 0


def test_zero_or_negative_earns_nothing():
    """ตาข่ายรับ — ยอดพวกนี้ไม่ควรมาถึงตรงนี้ แต่ถ้ามาต้องไม่ได้แต้มติดลบ"""
    assert points_for(0) == 0
    assert points_for(-500) == 0


def test_rate_is_overridable_for_future_per_shop_rates():
    """เตรียมไว้สำหรับวันที่แต่ละร้านใช้อัตราต่างกัน (งาน Step 5)"""
    assert points_for(250, baht_per_point=25) == 10
