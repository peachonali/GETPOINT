"""ตัวระบุตัวตนของใบเสร็จ — "ใบนี้คือใบไหน"

มี 2 ระดับ ใช้คนละจังหวะ:

    image_fingerprint    — จาก "ไฟล์รูป" · รู้ทันทีตอนอัปโหลด (ก่อน OCR)
                           จับได้เฉพาะ "ไฟล์เดียวกันเป๊ะ" เช่นกดส่งซ้ำ/เน็ตกระตุก

    content_fingerprint  — จาก "เนื้อหาใบเสร็จ" · รู้หลัง OCR อ่านได้แล้ว
                           จับได้ถึง "ใบเดียวกันแต่ถ่ายใหม่คนละรูป"

★ สิ่งที่เปลี่ยนจากเวอร์ชันแรก และเหตุผล (สำคัญมาก อย่าเปลี่ยนกลับ):

  เวอร์ชันแรกใช้ ชื่อร้าน + เลขที่ + วันที่ + ยอด
  วัดกับใบเสร็จจริง 28 รูปแล้วพบว่า **ชื่อร้านอ่านได้ไม่คงที่ระหว่างรูปของใบเดียวกัน**
      ใบ KFC 149 ใบเดียวกัน  รูปหนึ่งได้ "CRG-KFC 12IO2 (KEC-BIO C NAKORNSAVAN)"
                             อีกรูปได้ "2330 Host: Prapapan #2330 BOX AI1 Easy"
  → ลายนิ้วมือคนละค่า → ลูกค้าถ่ายใบเดิมส่งซ้ำได้แต้มสองเท่า
  จึง **ตัดชื่อร้านออกจากลายนิ้วมือ** แล้วใช้เลขอ้างอิงเป็นตัวหลักแทน

★ ลายนิ้วมือ "ไม่ใช่" ตัวตัดสินสุดท้ายว่าใบซ้ำ — ตัวตัดสินคือ `receipt_check/duplicate_check.py`
  เพราะการเทียบด้วยแฮชทำได้แค่ "เหมือนกันเป๊ะ" แต่ใบเสร็จใบเดียวกันที่ถ่ายคนละมุม
  OCR อ่านได้ไม่เท่ากันเสมอ ต้องเทียบแบบ "ใกล้เคียงพอ" ซึ่งแฮชทำไม่ได้โดยธรรมชาติ

ผูก tenant_id ไว้ในทั้งสองค่า — คนละแบรนด์ต้องไม่ชนกันแม้ใบเสร็จเหมือนกันทุกอย่าง
"""
from __future__ import annotations

import hashlib
from datetime import date

#: ตัดให้สั้นพอเก็บ/อ่าน/ใส่ query string ได้สบาย แต่ยาวพอไม่ชนกันเอง
#: 32 ตัวอักษร hex = 128 bit — โอกาสชนกันต่ำมากจนไม่ต้องคิดถึงที่ปริมาณของเรา
_FINGERPRINT_LENGTH = 32

_UNKNOWN = "?"


def image_fingerprint(tenant_id: str, image: bytes) -> str:
    """ลายนิ้วมือของ "ไฟล์รูป" — ไฟล์เดียวกันเป๊ะจะได้ค่าเดียวกัน

    ใช้ตอนรับอัปโหลด เพื่อจับการส่งซ้ำแบบทันทีโดยยังไม่ต้องรอ OCR (ประหยัด worker)
    ⚠ ถ่ายใบเดิมใหม่ = คนละไฟล์ = คนละค่า → จับไม่ได้ ต้องพึ่ง duplicate_check
    """
    digest = hashlib.sha256()
    digest.update(tenant_id.encode("utf-8"))
    digest.update(b"\x00")  # คั่นกัน tenant "a" + รูป "bc" ชนกับ tenant "ab" + รูป "c"
    digest.update(image)
    return digest.hexdigest()[:_FINGERPRINT_LENGTH]


def content_fingerprint(
    tenant_id: str,
    *,
    reference_codes: list[str] | None,
    receipt_no: str | None,
    receipt_date: date | None,
    total_amount: float,
) -> str:
    """ลายนิ้วมือของ "เนื้อหาใบเสร็จ" — ใช้เป็นทางลัดจับใบซ้ำแบบตรงเป๊ะ

    เลือกตัวระบุตามลำดับความน่าเชื่อถือ:
        1. เลขอ้างอิงของธุรกรรม (Invoice ID / TRANS ID / Tax INV) — เสถียรที่สุด
        2. เลขที่ใบเสร็จที่อ่านได้จากคำสำคัญ
        3. ไม่มีเลยก็ใช้แค่วันที่ + ยอด (อ่อน — duplicate_check จะเป็นตัวตัดสินแทน)

    ★ เมื่อมีเลขอ้างอิงหลายตัว ใช้ "ตัวที่น้อยที่สุดเมื่อเรียง" ไม่ใช่ทั้งชุด
      เพราะรูปคนละมุมของใบเดียวกันอ่านเลขได้ "ไม่ครบเท่ากัน" — แฮชทั้งชุดจะเพี้ยนทันที
      ที่รูปหนึ่งอ่านได้เกินมาหนึ่งตัว (วัดจริง: สลิป KFC รูปหนึ่งได้ 4 ตัว อีกรูปได้ 5 ตัว
      แต่ตัวที่น้อยที่สุดเมื่อเรียงตรงกันทั้งคู่)

    ปัดยอดเป็น 2 ตำแหน่งก่อนแฮช เพื่อให้ 250.0 กับ 250.00 ได้ค่าเดียวกัน
    """
    identity = _strongest_identity(reference_codes, receipt_no)
    parts = [
        tenant_id,
        identity,
        receipt_date.isoformat() if receipt_date else _UNKNOWN,
        f"{total_amount:.2f}",
    ]
    joined = "\x00".join(parts).encode("utf-8")  # คั่นด้วย NUL กันค่าติดกันจนกำกวม
    return hashlib.sha256(joined).hexdigest()[:_FINGERPRINT_LENGTH]


def _strongest_identity(reference_codes: list[str] | None, receipt_no: str | None) -> str:
    if reference_codes:
        return min(code.strip().lower() for code in reference_codes if code.strip())
    if receipt_no and receipt_no.strip():
        return receipt_no.strip().lower()
    return _UNKNOWN
