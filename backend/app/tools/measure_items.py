"""★ วัดการอ่าน "รายการสินค้า" เทียบเฉลย

วิธีใช้ (รันจาก backend/):
    python -m app.tools.measure_items
    python -m app.tools.measure_items --show      ← โชว์ชื่อที่อ่านได้เทียบเฉลยทีละรายการ
    python -m app.tools.measure_items --fresh     ← อ่าน OCR ใหม่ (เมื่อแก้โค้ด OCR)

★ วัด 3 อย่าง เพราะแต่ละอย่างตอบคนละคำถาม:

    ผลรวม = ยอดรวม   → "อ่านราคาถูกไหม" · เป็นหลักฐานทางคณิตศาสตร์ ปลอมยาก
                        นี่คือตัวชี้วัดที่สำคัญที่สุด เพราะเป็นสิ่งที่เอาไปใช้ตรวจ
                        template ได้จริง (Step 5)

    จำนวนรายการ      → "แบ่งรายการถูกไหม" · OCR หั่นบรรทัดเพี้ยนจะเห็นตรงนี้

    ★ ชื่อใกล้เคียง  → "อ่านชื่อสินค้าได้แค่ไหน" · ตัวนี้ต่ำแปลว่าต้องมีพจนานุกรมไทย
                        มาช่วยแก้คำที่ OCR อ่านเพี้ยน (ตามที่ตกลงกันไว้)
                        วัดแบบ "คล้ายพอ" ไม่ใช่ตรงเป๊ะ เพราะกระดาษความร้อนอ่านเพี้ยนเป็นปกติ
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.receipt_data.line_items import LineItem, find_line_items, items_match_total
from app.tools.golden_set import Reading, load_truth, read_all

#: ชื่อที่คล้ายกันเกินค่านี้ถือว่า "อ่านได้" — 0.6 คือระดับที่คนอ่านแล้วเดาออกว่าคืออะไร
#: ("Crispystrip" vs "[4] CrispyStrip" = 0.79 · "OREO SUNDAE" vs "OREO SUNDAE" = 1.0)
_NAME_SIMILARITY = 0.6


@dataclass
class Outcome:
    name: str
    expected: list[dict]
    got: list[LineItem]
    sum_ok: bool

    @property
    def count_ok(self) -> bool:
        return len(self.got) == len(self.expected)

    @property
    def matched_names(self) -> int:
        """เฉลยกี่รายการที่หาคู่ที่ "คล้ายพอ" ในสิ่งที่อ่านได้เจอ"""
        pool = [item.name for item in self.got]
        found = 0
        for want in self.expected:
            best = max((_similar(want["name"], got) for got in pool), default=0.0)
            if best >= _NAME_SIMILARITY:
                found += 1
        return found


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    truth = load_truth()
    readings = read_all(fresh="--fresh" in args)

    outcomes = [
        _measure_one(readings[name], truth[name])
        for name in sorted(readings, key=_number)
        if truth[name]["items"]          # ใบที่เฉลยยังอ่านไม่ออก ไม่เอามาวัด
    ]

    _report(outcomes)
    if "--show" in args:
        _show_details(outcomes)
    return 0


def _measure_one(reading: Reading, expected: dict) -> Outcome:
    items = find_line_items(reading.lines, total_amount=reading.total_amount)
    sum_ok = (
        items_match_total(items, reading.total_amount)
        if reading.total_amount is not None else False
    )
    return Outcome(reading.name, expected["items"], items, sum_ok)


def _report(outcomes: list[Outcome]) -> None:
    print(f"{'ใบ':>5} | {'เฉลย':>5} | {'อ่านได้':>7} | {'ผลรวม=ยอด':<10} | ชื่อที่ตรง")
    print("-" * 62)
    for o in outcomes:
        print(
            f"{_short(o.name):>5} | {len(o.expected):>5} | {len(o.got):>7} | "
            f"{'ถูก' if o.sum_ok else '-':<10} | {o.matched_names}/{len(o.expected)}"
        )

    total = len(outcomes)
    sum_ok = sum(1 for o in outcomes if o.sum_ok)
    count_ok = sum(1 for o in outcomes if o.count_ok)
    names_found = sum(o.matched_names for o in outcomes)
    names_total = sum(len(o.expected) for o in outcomes)

    print("-" * 62)
    print(f"  {'★ ผลรวมราคา = ยอดรวม':<34} {sum_ok:>3}/{total}  ({sum_ok / total * 100:.0f}%)")
    print(f"  {'จำนวนรายการตรงเฉลย':<34} {count_ok:>3}/{total}  ({count_ok / total * 100:.0f}%)")
    print(
        f"  {'★ ชื่อสินค้าที่อ่านได้ใกล้เคียง':<34} "
        f"{names_found:>3}/{names_total}  ({names_found / names_total * 100:.0f}%)"
    )


def _show_details(outcomes: list[Outcome]) -> None:
    for o in outcomes:
        print(f"\n=== {_short(o.name)} ===")
        print("  เฉลย  :", ", ".join(f"{i['name']}={i['price']}" for i in o.expected))
        print("  อ่านได้:", ", ".join(f"{i.name}={i.price}" for i in o.got) or "(ไม่พบ)")


def _similar(left: str, right: str) -> float:
    return SequenceMatcher(None, left.lower().strip(), right.lower().strip()).ratio()


def _short(name: str) -> str:
    return "#" + name.split("_")[-1].replace(".jpg", "")


def _number(name: str) -> int:
    digits = "".join(char for char in name.split("_")[-1] if char.isdigit())
    return int(digits) if digits else 0


if __name__ == "__main__":
    sys.exit(main())
