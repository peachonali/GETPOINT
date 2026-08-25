"""โหลดชุดทดสอบใบเสร็จจริง + แคช "บรรทัดที่ OCR อ่านได้" ไว้ใช้ซ้ำ

★ ทำไมต้องมีแคช: การอ่านใบเสร็จ 28 ใบใช้เวลาราว 4 นาที
  เครื่องมือวัดมีหลายตัว (ยอดเงิน / ทุก field / การกันใบซ้ำ) ถ้าแต่ละตัวอ่านใหม่เอง
  จะเสียเวลารวมเป็นสิบนาทีต่อการแก้โค้ดหนึ่งครั้ง → คนจะเลิกรันเครื่องมือวัด
  ซึ่งแปลว่าเรากลับไปเดาแทนการวัด

★★ แคชเก็บ "บรรทัดดิบจาก OCR" เท่านั้น ไม่เก็บค่าที่แยก field แล้ว
   เหตุผล: การแยก field (ยอด/วันที่/เวลา/เลขอ้างอิง) คือส่วนที่เราแก้บ่อยที่สุด
   ถ้าแคชเก็บผลหลังแยก field ไว้ด้วย พอแก้ตัวแยก field แล้วรันวัดใหม่
   จะได้ "ตัวเลขของโค้ดเวอร์ชันเก่า" โดยไม่มีอะไรเตือน — เครื่องมือวัดที่โกหก
   อันตรายกว่าไม่มีเครื่องมือวัดเลย
   → ตอนนี้แคชครอบเฉพาะขั้นที่ช้าและไม่ค่อยเปลี่ยน (เตรียมรูป + OCR)
     ส่วนขั้นที่เปลี่ยนบ่อยถูกคำนวณใหม่ทุกครั้ง ใช้เวลาไม่ถึงวินาที

★ แคชผูกกับ "เวลาแก้ไขไฟล์รูป" — แก้รูป/เพิ่มรูปแล้วแคชหมดอายุเอง
  ⚠ แต่แคชไม่รู้ว่าโค้ด OCR/image_prep เปลี่ยน! แก้สองส่วนนั้นเมื่อไหร่ ต้องสั่ง --fresh
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, time as clock
from pathlib import Path

from app.image_prep.image_pipeline import prepare_for_ocr
from app.receipt_data.field_extractor import extract_receipt_fields
from app.reliability.errors import GetpointError

#: backend/app/tools/golden_set.py → ขึ้น 3 ชั้นถึง repo root
_ROOT = Path(__file__).resolve().parents[3]
RECEIPTS_DIR = _ROOT / "tests" / "fixtures" / "receipts"
GROUND_TRUTH = _ROOT / "tests" / "fixtures" / "expected" / "receipts_ground_truth.json"
_CACHE = _ROOT / "tests" / "fixtures" / "expected" / ".ocr_cache.json"


@dataclass
class Reading:
    """สิ่งที่ระบบอ่านได้จากรูป 1 รูป · อ่านยอดไม่ได้ → failure มีค่า และ total_amount เป็น None"""

    name: str
    seconds: float
    lines: list[str]
    total_amount: float | None = None
    merchant: str | None = None
    merchant_code: str | None = None
    receipt_no: str | None = None
    receipt_date: date | None = None
    receipt_time: clock | None = None
    reference_codes: list[str] | None = None
    failure: str | None = None

    @property
    def read_ok(self) -> bool:
        return self.total_amount is not None


def load_truth() -> dict[str, dict]:
    """เฉลยที่คนกรอกจากการดูรูปจริง (ดู tests/fixtures/expected/README.md)"""
    return json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))


def read_all(*, fresh: bool = False) -> dict[str, Reading]:
    """อ่านใบเสร็จทุกใบในชุดทดสอบผ่านระบบจริง

    ขั้น OCR ใช้แคชถ้ามี · ขั้นแยก field คำนวณใหม่ทุกครั้งเสมอ
    """
    raw_lines = _ocr_lines(fresh=fresh)
    return {
        name: _extract(name, lines, seconds)
        for name, (lines, seconds) in raw_lines.items()
    }


def _ocr_lines(*, fresh: bool) -> dict[str, tuple[list[str], float]]:
    if not fresh:
        cached = _load_cache()
        if cached is not None:
            print(f"(ใช้บรรทัด OCR จากแคช {_CACHE.name} — สั่ง --fresh เพื่ออ่านรูปใหม่)\n")
            return cached

    print("กำลังโหลด OCR แล้วอ่านใบเสร็จทั้งชุด (ใช้เวลาสักครู่)...\n")
    from app.ocr.paddle_ocr import PaddleOcr

    ocr = PaddleOcr()
    result = {path.name: _read_lines(path, ocr) for path in _images()}
    _save_cache(result)
    return result


def _read_lines(path: Path, ocr) -> tuple[list[str], float]:
    started = time.perf_counter()
    try:
        lines = ocr.read(prepare_for_ocr(path.read_bytes())).lines()
    except GetpointError as exc:
        # รูปถูกตีกลับตั้งแต่ขั้นเตรียมรูป (เบลอ/มืดเกิน) — เป็นคำตอบที่ยอมรับได้
        lines = [f"__REJECTED__ {exc}"]
    except Exception as exc:  # noqa: BLE001 — เครื่องมือวัดต้องไม่ตายกลางทาง
        lines = [f"__ERROR__ {type(exc).__name__}: {exc}"]
    return lines, time.perf_counter() - started


def _extract(name: str, lines: list[str], seconds: float) -> Reading:
    """แยก field จากบรรทัดที่ OCR อ่านได้ — ขั้นนี้รันใหม่ทุกครั้ง ไม่ผ่านแคช"""
    if lines and lines[0].startswith(("__REJECTED__", "__ERROR__")):
        return Reading(name, seconds, lines, failure=lines[0])

    from app.ocr.ocr_result import OcrResult, TextBox

    # ประกอบ OcrResult กลับจากบรรทัด: ให้แต่ละบรรทัดเป็นกล่องเดียวที่ไม่ทับกันแนวตั้ง
    # (field_extractor ใช้แค่ผลของ .lines() จึงได้ผลเท่ากับตอนอ่านจากรูปจริง)
    boxes = [TextBox(text=line, bbox=(0, index * 100, 1000, index * 100 + 50))
             for index, line in enumerate(lines)]

    try:
        fields = extract_receipt_fields(OcrResult(boxes=boxes))
    except GetpointError as exc:
        return Reading(name, seconds, lines, failure=str(exc))

    return Reading(
        name=name,
        seconds=seconds,
        lines=lines,
        total_amount=fields["total_amount"],
        merchant=fields["merchant"],
        merchant_code=fields["merchant_code"],
        receipt_no=fields["receipt_no"],
        receipt_date=fields["receipt_date"],
        receipt_time=fields["receipt_time"],
        reference_codes=fields["reference_codes"],
    )


def _images() -> list[Path]:
    """เรียงตามเลขท้ายชื่อไฟล์ — ให้ผลลัพธ์เรียงเหมือนกันทุกครั้ง (เทียบ diff ได้)"""
    return sorted(RECEIPTS_DIR.glob("*.jpg"), key=_number_in_name)


def _number_in_name(path: Path) -> int:
    digits = "".join(char for char in path.stem.split("_")[-1] if char.isdigit())
    return int(digits) if digits else 0


# ═══════════════════════════════════════════
# แคช
# ═══════════════════════════════════════════

def _load_cache() -> dict[str, tuple[list[str], float]] | None:
    if not _CACHE.is_file():
        return None

    try:
        raw = json.loads(_CACHE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None  # แคชเสีย — อ่านใหม่ ดีกว่าพัง

    if raw.get("source_stamp") != _source_stamp():
        return None  # รูปในชุดทดสอบเปลี่ยนไปแล้ว

    return {name: (item["lines"], item["seconds"]) for name, item in raw["readings"].items()}


def _save_cache(result: dict[str, tuple[list[str], float]]) -> None:
    payload = {
        "source_stamp": _source_stamp(),
        "readings": {
            name: {"lines": lines, "seconds": seconds}
            for name, (lines, seconds) in result.items()
        },
    }
    _CACHE.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def _source_stamp() -> str:
    """ลายเซ็นของชุดรูป — เปลี่ยนเมื่อไฟล์ถูกเพิ่ม/ลบ/แก้ไข"""
    return "|".join(f"{path.name}:{path.stat().st_mtime_ns}" for path in _images())
