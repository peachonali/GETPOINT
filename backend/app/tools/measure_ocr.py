"""วัดความแม่นของ OCR เทียบกับเฉลยจริง — ตัวชี้วัดหลักของ Step 4

วิธีใช้ (รันจาก backend/):
    python -m app.tools.measure_ocr

อ่านเฉลยจาก tests/fixtures/expected/receipts_ground_truth.json
แล้ววิ่งใบเสร็จทุกใบใน tests/fixtures/receipts/ ผ่านระบบจริง

★ แยกผลเป็น 3 กอง เพราะความหมายต่างกันมาก:
    ถูก        — ให้แต้มถูก
    ★ ผิด      — ให้แต้มผิด (ร้ายแรงที่สุด · ลูกค้าไม่รู้ตัว ระบบก็ไม่รู้ตัว)
    อ่านไม่ได้ — ลูกค้าถ่ายใหม่ได้ (น่ารำคาญ แต่ไม่เสียหาย)

เป้าหมาย: "ผิด = 0" มาก่อน "อ่านได้เยอะ" เสมอ
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from app.image_prep.image_pipeline import prepare_for_ocr
from app.receipt_data.field_extractor import extract_receipt_fields
from app.reliability.errors import GetpointError

#: ไฟล์นี้อยู่ backend/app/tools/measure_ocr.py → ขึ้น 3 ชั้นถึง repo root
_ROOT = Path(__file__).resolve().parents[3]
RECEIPTS_DIR = _ROOT / "tests" / "fixtures" / "receipts"
GROUND_TRUTH = _ROOT / "tests" / "fixtures" / "expected" / "receipts_ground_truth.json"

#: ยอมต่างได้เท่านี้ถึงนับว่าถูก (ปัดเศษสตางค์)
TOLERANCE = 0.01


@dataclass
class Outcome:
    name: str
    expected: float
    actual: float | None
    seconds: float

    @property
    def correct(self) -> bool:
        return self.actual is not None and abs(self.actual - self.expected) <= TOLERANCE

    @property
    def wrong(self) -> bool:
        return self.actual is not None and not self.correct


def main() -> int:
    if not GROUND_TRUTH.is_file():
        print(f"ไม่พบไฟล์เฉลย: {GROUND_TRUTH}")
        return 1

    truth = {
        name: data["expected_total"]
        for name, data in json.loads(GROUND_TRUTH.read_text(encoding="utf-8")).items()
        if data.get("expected_total") is not None
    }
    if not truth:
        print("ไฟล์เฉลยยังไม่ได้กรอก (expected_total เป็น null ทั้งหมด)")
        return 1

    print(f"กำลังโหลด OCR แล้ววัดกับใบเสร็จ {len(truth)} ใบ...\n")
    from app.ocr.paddle_ocr import PaddleOcr

    ocr = PaddleOcr()
    outcomes = [_run_one(name, expected, ocr) for name, expected in sorted(truth.items(), key=_order)]

    _report(outcomes)
    # ออกด้วยรหัสผิดพลาดถ้ามีใบที่อ่าน "ผิด" — ใช้ต่อใน CI ได้
    return 1 if any(o.wrong for o in outcomes) else 0


def _run_one(name: str, expected: float, ocr) -> Outcome:
    path = RECEIPTS_DIR / name
    started = time.perf_counter()
    actual: float | None = None

    if path.is_file():
        try:
            fields = extract_receipt_fields(ocr.read(prepare_for_ocr(path.read_bytes())))
            actual = fields["total_amount"]
        except GetpointError:
            actual = None  # ระบบบอกเองว่าอ่านไม่ได้ — ถือเป็นคำตอบที่ยอมรับได้
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ {name}: พังแบบไม่คาดคิด — {type(exc).__name__}: {exc}")

    return Outcome(name, expected, actual, time.perf_counter() - started)


def _report(outcomes: list[Outcome]) -> None:
    correct = [o for o in outcomes if o.correct]
    wrong = [o for o in outcomes if o.wrong]
    missed = [o for o in outcomes if o.actual is None]

    print(f"{'ใบ':>6} | {'เฉลย':>9} | {'ระบบอ่าน':>9} | {'วินาที':>6} | ผล")
    print("-" * 56)
    for o in outcomes:
        got = f"{o.actual:,.2f}" if o.actual is not None else "-"
        mark = "ถูก" if o.correct else ("★ ผิด" if o.wrong else "อ่านไม่ได้")
        print(f"{_short(o.name):>6} | {o.expected:9,.2f} | {got:>9} | {o.seconds:6.1f} | {mark}")

    total = len(outcomes)
    print("-" * 56)
    print(f"  ถูก        {len(correct):>3}/{total}  ({len(correct)/total*100:.0f}%)")
    print(f"  ★ ผิด      {len(wrong):>3}/{total}  ({len(wrong)/total*100:.0f}%)   ← ต้องเป็น 0")
    print(f"  อ่านไม่ได้ {len(missed):>3}/{total}  ({len(missed)/total*100:.0f}%)")

    if outcomes:
        print(f"  เวลาเฉลี่ย {sum(o.seconds for o in outcomes)/total:.1f} วินาที/ใบ")

    if wrong:
        print("\n★ ใบที่อ่านผิด (อันตรายที่สุด — ต้องแก้ก่อน):")
        for o in wrong:
            print(f"    {_short(o.name)}: เฉลย {o.expected:,.2f} แต่ระบบได้ {o.actual:,.2f}")


def _short(name: str) -> str:
    return "#" + name.split("_")[-1].replace(".jpg", "")


def _order(item: tuple[str, float]) -> int:
    digits = "".join(c for c in item[0].split("_")[-1] if c.isdigit())
    return int(digits) if digits else 0


if __name__ == "__main__":
    sys.exit(main())
