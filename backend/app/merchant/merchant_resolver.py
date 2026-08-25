"""ตัวคุม: ใบเสร็จใบนี้มาจากร้านไหน — รู้จักแล้ว หรือเป็นร้านใหม่

★ นี่คือ "จุดที่การตัดสินใจเรื่องร้านเกิดขึ้น" ที่เดียวของระบบ
  ชั้นบน (field_extractor / scan_job) ถามที่นี่ที่เดียว ไม่ต้องรู้ว่าเบื้องหลัง
  ใช้ทะเบียนร้าน ใช้ template หรือใช้ AI

เส้นทาง:
    รู้จักร้าน   → ใช้ทะเบียน (known_merchant) · ได้รหัสร้านที่คงที่ + ชื่อที่ถูกต้อง
    ไม่รู้จัก    → คืนชื่อดิบที่ OCR อ่านได้ พร้อม is_known=False
                   (Step 5 ต่อไป: ส่งให้ gemini_resolver เสนอ template แล้วรอคนอนุมัติ)

★ ทำไมยังไม่ต่อ Gemini วันนี้:
    ผลจาก AI เชื่อไม่ได้โดยตรง ต้องมี template_rules คอยตรวจก่อนเสมอ (CONTEXT ข้อ 3)
    และต้องมี prompt_guard กัน prompt injection ผ่านข้อความบนใบเสร็จก่อนด้วย
    ทั้งสองอย่างยังไม่ได้เขียน — ต่อ AI ก่อนมีตัวกรองคือการเปิดช่องให้ผลลัพธ์ที่
    ควบคุมไม่ได้ไหลเข้าไปถึงการให้แต้ม
"""
from __future__ import annotations

from dataclasses import dataclass

from app.merchant.known_merchant import KnownMerchant, identify
from app.receipt_data.merchant_name import find_merchant

#: ชื่อที่ใช้เมื่ออ่านอะไรไม่ได้เลย — ต้องไม่ทำให้ลูกค้าเห็นข้อความว่างเปล่า
_UNKNOWN_DISPLAY_NAME = "ไม่ทราบร้าน"


@dataclass(frozen=True)
class ResolvedMerchant:
    """ผลการตัดสินว่าใบเสร็จนี้มาจากร้านไหน"""

    #: รหัสร้านที่คงที่ (kfc / dq / ...) · None = ยังไม่รู้จักร้านนี้
    #: ★ ใช้ตัวนี้ตัดสินใจเท่านั้น ห้ามใช้ display_name — ชื่อเปลี่ยนได้ รหัสไม่เปลี่ยน
    code: str | None
    #: ชื่อที่แสดงให้ลูกค้าเห็น
    display_name: str
    #: ชื่อดิบตามที่ OCR อ่านได้ — เก็บไว้ debug และไว้ให้คนดูตอนขึ้นทะเบียนร้านใหม่
    raw_name: str | None

    @property
    def is_known(self) -> bool:
        return self.code is not None


def resolve(lines: list[str]) -> ResolvedMerchant:
    """ตัดสินว่าใบเสร็จนี้มาจากร้านไหน · ไม่รู้จักก็ยังคืนค่าเสมอ (ไม่โยน error)

    ร้านที่ยังไม่รู้จักไม่ใช่ความผิดพลาด — เป็นสถานการณ์ปกติที่ระบบต้องรองรับ
    ลูกค้ายังต้องได้แต้มจากยอดเงินที่อ่านได้ แม้เราจะยังไม่มี template ของร้านนั้น
    """
    raw_name = find_merchant(lines)
    known = identify(lines)

    if known is None:
        return ResolvedMerchant(
            code=None,
            display_name=raw_name or _UNKNOWN_DISPLAY_NAME,
            raw_name=raw_name,
        )

    return _from_known(known, raw_name)


def _from_known(known: KnownMerchant, raw_name: str | None) -> ResolvedMerchant:
    """★ ใช้ชื่อจากทะเบียน ไม่ใช่ชื่อที่ OCR อ่านได้

    เพราะชื่อที่ OCR อ่านได้เป็นข้อความมั่วบ่อยมาก และลูกค้าเป็นคนเห็นค่านี้
    เจอจริง: ใบ KFC ใบเดียวกันสองมุม ได้ชื่อร้านคนละเรื่อง
        "CRG-KFC 12IO2 (KEC-BIO C NAKORNSAVAN)" กับ "2330 Host: Prapapan #2330"
    """
    return ResolvedMerchant(code=known.code, display_name=known.display_name, raw_name=raw_name)
