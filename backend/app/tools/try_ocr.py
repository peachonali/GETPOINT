"""ลองอ่านใบเสร็จจริงด้วยระบบของเรา แล้วดูผลทันที

วิธีใช้ (รันจาก backend/):
    python -m app.tools.try_ocr "C:\\path\\ใบเสร็จ.jpg"
    python -m app.tools.try_ocr ..\\tests\\fixtures\\receipts     ← ทั้งโฟลเดอร์
    python -m app.tools.try_ocr รูป.jpg --save-prepared           ← เก็บรูปหลังปรับไว้ดู

บอกอะไรบ้าง:
    - คุณภาพรูปผ่านเกณฑ์ไหม (เบลอ/มืด) และค่าที่วัดได้
    - OCR อ่านได้กี่บรรทัด อ่านว่าอะไร
    - ★ ระบบสรุปได้ว่า "ยอดเงินเท่าไหร่" — ตัวเลขนี้คือสิ่งที่จะกลายเป็นแต้ม
    - ใช้เวลาไปกี่วินาที (เทียบกับ SLO < 15 วิ)

★ มีไว้เพื่อวัดความแม่นกับใบเสร็จจริงก่อนเปิดใช้งาน — ถ้าอ่านยอดผิด
  จะเห็นตรงนี้ทันที ไม่ต้องรอลูกค้าร้องเรียน
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from app.image_prep.image_pipeline import prepare_for_ocr
from app.image_prep.image_quality import assess_quality
from app.receipt_data.field_extractor import extract_receipt_fields
from app.reliability.errors import InputValidationError

#: นามสกุลที่รองรับ (ตรงกับ upload_check)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    images = _collect_images(args.path)

    if not images:
        print(f"ไม่พบไฟล์รูปใน {args.path}")
        return 1

    # โหลด OCR ครั้งเดียวแล้วใช้กับทุกไฟล์ (โหลดโมเดลใช้เวลา ~20 วินาที)
    print("กำลังเตรียม OCR (ครั้งแรกใช้เวลาสักครู่)...\n")
    from app.ocr.paddle_ocr import PaddleOcr

    ocr = PaddleOcr()

    results = [_try_one(path, ocr, save_prepared=args.save_prepared) for path in images]
    _print_summary(results)
    return 0


def _try_one(path: Path, ocr, *, save_prepared: bool) -> bool:
    """ลองอ่าน 1 ใบ · คืน True ถ้าอ่านยอดได้"""
    print("=" * 70)
    print(f"📄 {path.name}")
    print("=" * 70)

    raw = path.read_bytes()
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        print("  ❌ เปิดไฟล์ไม่ได้ (ไฟล์เสียหรือไม่ใช่รูป)\n")
        return False

    report = assess_quality(image)
    print(f"  ขนาด      {image.shape[1]}x{image.shape[0]} px")
    print(f"  ความชัด   {report.blur_score:.0f}  (ต่ำกว่า 60 = เบลอเกิน)")
    print(f"  ความสว่าง {report.brightness:.0f}  (ต้องอยู่ 40-240)")

    started = time.perf_counter()
    try:
        prepared = prepare_for_ocr(raw)
    except InputValidationError as exc:
        print(f"  ❌ ตีกลับ: {exc}\n")
        return False

    if save_prepared:
        out = path.with_name(f"{path.stem}__prepared.jpg")
        out.write_bytes(prepared)
        print(f"  💾 บันทึกรูปหลังปรับไว้ที่ {out.name}")

    result = ocr.read(prepared)
    elapsed = time.perf_counter() - started

    print(f"\n  อ่านได้ {len(result.boxes)} บรรทัด:")
    for box in result.boxes:
        print(f"     {box.text}")

    try:
        fields = extract_receipt_fields(result)
    except InputValidationError as exc:
        print(f"\n  ❌ สรุปไม่ได้: {exc}")
        print(f"  ⏱  {elapsed:.1f}s\n")
        return False

    print("\n  ── ระบบสรุปได้ว่า ──")
    print(f"     ร้าน       {fields['merchant']}")
    print(f"     เลขที่     {fields['receipt_no'] or '(ไม่พบ)'}")
    print(f"     วันที่     {fields['receipt_date'] or '(ไม่พบ)'}")
    print(f"  ★  ยอดเงิน   {fields['total_amount']:,.2f} บาท   ← ตัวเลขที่จะกลายเป็นแต้ม")
    print(f"  ⏱  {elapsed:.1f}s\n")
    return True


def _print_summary(results: list[bool]) -> None:
    total = len(results)
    ok = sum(results)
    print("=" * 70)
    print(f"สรุป: อ่านยอดได้ {ok}/{total} ใบ", end="")
    if total:
        print(f"  ({ok / total * 100:.0f}%)")
    print("=" * 70)
    if ok < total:
        print("\nใบที่อ่านไม่ได้ ให้ดูว่าเป็นเพราะรูป (เบลอ/มืด) หรือเพราะรูปแบบใบเสร็จ")
        print("ถ้าเป็นรูปแบบใบเสร็จ = ต้องมี template ของร้านนั้น (งาน Step 5)")


def _collect_images(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(
            p for p in path.iterdir()
            if p.suffix.lower() in IMAGE_SUFFIXES and "__prepared" not in p.stem
        )
    return []


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ลองอ่านใบเสร็จด้วยระบบ GETPOINT")
    parser.add_argument("path", type=Path, help="ไฟล์รูป หรือโฟลเดอร์ที่มีรูป")
    parser.add_argument(
        "--save-prepared", action="store_true",
        help="บันทึกรูปหลังผ่าน image_prep ไว้ดูว่าตัด/ดัดถูกไหม",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main())
