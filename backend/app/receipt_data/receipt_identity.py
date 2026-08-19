"""ตัวระบุตัวตนของใบเสร็จ — "ใบนี้คือใบไหน" ใช้กันซ้ำ + เป็น reference ตอนส่ง CRM

★ ทำไมสำคัญมาก: นี่คือสิ่งที่กัน "แต้มซ้ำ" ซึ่งเป็นความเสียหายที่แก้ยากที่สุด
  (ลูกค้าถ่ายใบเดิมส่งซ้ำ / กดปุ่มรัว / worker ทำงานซ้ำหลังระบบล่ม)

มี 2 ระดับ ใช้คนละจังหวะ:

    image_fingerprint  — จาก "ไฟล์รูป" · รู้ได้ทันทีตอนอัปโหลด (ก่อน OCR)
                         จับได้เฉพาะ "ไฟล์เดียวกันเป๊ะ" เช่นกดส่งซ้ำ/เน็ตกระตุก

    receipt_fingerprint — จาก "เนื้อหาใบเสร็จ" · รู้หลัง OCR อ่านได้แล้ว
                         จับได้ถึง "ใบเดียวกันแต่ถ่ายใหม่คนละรูป" ซึ่งเป็นเคสที่ตั้งใจโกง
                         ★ ตัวนี้คือค่าที่ส่งเป็น reference ให้ CRM (ADR 0003 #7:
                           reference ซ้ำ = CRM ถือเป็นรายการเดิม ไม่บันทึกซ้ำ)

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
    ⚠ ถ่ายใบเดิมใหม่ = คนละไฟล์ = คนละค่า → จับไม่ได้ ต้องพึ่ง receipt_fingerprint
    """
    digest = hashlib.sha256()
    digest.update(tenant_id.encode("utf-8"))
    digest.update(b"\x00")  # คั่นกัน tenant "a" + รูป "bc" ชนกับ tenant "ab" + รูป "c"
    digest.update(image)
    return digest.hexdigest()[:_FINGERPRINT_LENGTH]


def receipt_fingerprint(
    tenant_id: str,
    *,
    merchant: str,
    receipt_no: str | None,
    receipt_date: date | None,
    total_amount: float,
) -> str:
    """ลายนิ้วมือของ "เนื้อหาใบเสร็จ" — ใบเดียวกันได้ค่าเดียวกันแม้ถ่ายคนละรูป

    เลือก 4 field นี้เพราะเป็นชุดที่เล็กที่สุดที่ระบุใบเสร็จได้จริง:
        ร้าน + เลขที่ใบเสร็จ + วันที่ + ยอดเงิน

    ⚠ ใบเสร็จบางร้านไม่มีเลขที่ (receipt_no = None) → ความแม่นลดลง
      กรณีนั้นจะอาศัย ร้าน+วันที่+ยอด ซึ่งอาจชนกันได้ถ้าซื้อสองครั้งยอดเท่ากันวันเดียวกัน
      เป็นข้อจำกัดที่ยอมรับไว้ (ฝั่งปลอดภัย: ให้แต้มน้อยไปดีกว่าให้ซ้ำ)
      → duplicate_check จะเป็นตัวตัดสินสุดท้ายอีกชั้น (Step 6)

    ปัดยอดเป็น 2 ตำแหน่งก่อนแฮช เพื่อให้ 250.0 กับ 250.00 ได้ค่าเดียวกัน
    """
    parts = [
        tenant_id,
        merchant.strip().lower(),
        (receipt_no or _UNKNOWN).strip().lower(),
        receipt_date.isoformat() if receipt_date else _UNKNOWN,
        f"{total_amount:.2f}",
    ]
    joined = "\x00".join(parts).encode("utf-8")  # คั่นด้วย NUL กันค่าติดกันจนกำกวม
    return hashlib.sha256(joined).hexdigest()[:_FINGERPRINT_LENGTH]
