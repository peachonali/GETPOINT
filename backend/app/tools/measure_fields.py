"""วัดความแม่นของ "ทุก field" เทียบเฉลย — ไม่ใช่แค่ยอดเงิน

วิธีใช้ (รันจาก backend/):
    python -m app.tools.measure_fields
    python -m app.tools.measure_fields --fresh   ← อ่าน OCR ใหม่ (ใช้เมื่อแก้โค้ด OCR)

★ ทำไมต้องวัดเกินยอดเงิน:
    ยอดเงินอย่างเดียวบอกได้แค่ว่า "ให้แต้มถูกไหม"
    แต่การกันใบซ้ำใช้ วันที่ + เวลา + เลขอ้างอิง ด้วย
    ถ้าไม่วัดสามตัวนี้ เราจะไม่มีทางรู้ว่าการกันซ้ำกำลังแย่ลงจากการแก้โค้ด OCR

★ แต่ละ field มีเกณฑ์ "ถูก" ไม่เหมือนกัน (ดูในแต่ละฟังก์ชัน) เพราะใช้งานคนละแบบ:
    ยอดเงิน     ต้องตรงเป๊ะ — กลายเป็นแต้มโดยตรง
    วันที่/เวลา  ต้องตรงเป๊ะ — ใช้ตัดสินว่าคนละครั้งหรือไม่
    เลขอ้างอิง  ขอแค่ "อ่านได้ตรงกันทั้งสองรูปของใบเดียวกัน" ไม่ต้องตรงกับเฉลย
                 (อ่านเพี้ยนเหมือนกันทั้งคู่ ก็ใช้กันซ้ำได้ดีเท่ากัน)
    ชื่อร้าน     ขอแค่ "มีคำของชื่อร้านจริงอยู่ในนั้น" — ใช้แค่แสดงให้ลูกค้าดู
"""
from __future__ import annotations

import sys
from datetime import datetime

from app.tools.golden_set import Reading, load_truth, read_all

#: ยอมต่างได้เท่านี้ถึงนับว่ายอดถูก (ปัดเศษสตางค์)
_AMOUNT_TOLERANCE = 0.01

#: เวลาบนใบเสร็จกับบนสลิปของการซื้อเดียวกันต่างกันได้เล็กน้อย — วัดแค่ ชั่วโมง:นาที
_TIME_FORMAT = "%H:%M"


def main(argv: list[str] | None = None) -> int:
    fresh = "--fresh" in (argv if argv is not None else sys.argv[1:])
    truth = load_truth()
    readings = read_all(fresh=fresh)
    names = sorted(readings, key=_number)

    print(f"{'ใบ':>5} | {'ยอดเงิน':<14} | {'วันที่':<7} | {'เวลา':<7} | {'เลขอ้างอิง':<10} | ร้าน")
    print("-" * 78)

    tally = {"amount": 0, "date": 0, "time": 0, "reference": 0, "merchant": 0}
    for name in names:
        reading, expected = readings[name], truth[name]
        marks = {
            "amount": _amount_ok(reading, expected),
            "date": _date_ok(reading, expected),
            "time": _time_ok(reading, expected),
            "reference": _reference_ok(reading, expected),
            "merchant": _merchant_ok(reading, expected),
        }
        for field, ok in marks.items():
            tally[field] += int(ok)

        got = f"{reading.total_amount:,.2f}" if reading.read_ok else "อ่านไม่ได้"
        print(
            f"{_short(name):>5} | {got:>8} {_mark(marks['amount']):<4} | "
            f"{_mark(marks['date']):<7} | {_mark(marks['time']):<7} | "
            f"{_mark(marks['reference']):<10} | {_mark(marks['merchant'])} "
            f"{(reading.merchant or '')[:30]}"
        )

    total = len(names)
    print("-" * 78)
    for field, label in (
        ("amount", "ยอดเงิน (ตรงเป๊ะ)"),
        ("date", "วันที่ (ตรงเป๊ะ)"),
        ("time", "เวลา (ตรงถึงนาที)"),
        ("reference", "เลขอ้างอิง (อ่านได้อย่างน้อย 1 ตัว)"),
        ("merchant", "ชื่อร้าน (มีคำของร้านจริง)"),
    ):
        print(f"  {label:<38} {tally[field]:>3}/{total}  ({tally[field] / total * 100:.0f}%)")

    seconds = [r.seconds for r in readings.values()]
    print(f"  {'เวลาเฉลี่ยต่อใบ':<38} {sum(seconds) / len(seconds):>5.1f} วินาที")
    return 0


# ═══════════════════════════════════════════
# เกณฑ์ "ถูก" ของแต่ละ field
# ═══════════════════════════════════════════

def _amount_ok(reading: Reading, expected: dict) -> bool:
    if not reading.read_ok:
        return False
    return abs(reading.total_amount - expected["expected_total"]) <= _AMOUNT_TOLERANCE


def _date_ok(reading: Reading, expected: dict) -> bool:
    if reading.receipt_date is None or not expected.get("date"):
        return False
    return reading.receipt_date.isoformat() == expected["date"]


def _time_ok(reading: Reading, expected: dict) -> bool:
    if reading.receipt_time is None or not expected.get("time"):
        return False
    want = datetime.strptime(expected["time"][:5], _TIME_FORMAT).time()
    return reading.receipt_time.strftime(_TIME_FORMAT) == want.strftime(_TIME_FORMAT)


def _reference_ok(reading: Reading, expected: dict) -> bool:
    """★ นับว่าถูกเมื่อ "อ่านได้อย่างน้อย 1 ตัว" ไม่ใช่ต้องตรงกับเฉลย

    เพราะหน้าที่ของเลขอ้างอิงคือ "อ่านได้ค่าเดิมทุกครั้ง" ไม่ใช่ "อ่านได้ถูกต้อง"
    วัดจริง: BigC #14/#17 อ่าน 727030981 เพี้ยนเป็น A030981 ทั้งสองรูปเหมือนกัน
    → ใช้กันใบซ้ำได้ผลเท่ากับอ่านถูก (ความ "ตรงกันข้ามรูป" วัดที่ measure_duplicate)
    """
    return bool(reading.reference_codes)


def _merchant_ok(reading: Reading, expected: dict) -> bool:
    """มีคำใดคำหนึ่งของชื่อร้านจริงอยู่ในสิ่งที่อ่านได้ไหม (ยาว ≥ 3 ตัวอักษร)

    เกณฑ์หลวมโดยตั้งใจ — ชื่อร้านใช้แค่แสดงให้ลูกค้าดู ไม่ได้ใช้ตัดสินอะไร
    (เคยใช้ตัดสินใบซ้ำแล้วพัง — ดู receipt_identity.py)
    """
    if not reading.merchant:
        return False
    got = reading.merchant.lower()
    words = [w for w in expected["merchant_text"].lower().replace("/", " ").split() if len(w) >= 3]
    return any(word in got for word in words)


def _mark(ok: bool) -> str:
    return "ถูก" if ok else "-"


def _short(name: str) -> str:
    return "#" + name.split("_")[-1].replace(".jpg", "")


def _number(name: str) -> int:
    digits = "".join(char for char in name.split("_")[-1] if char.isdigit())
    return int(digits) if digits else 0


if __name__ == "__main__":
    sys.exit(main())
