"""สัญญา (Port) ของผู้ช่วย AI — โดเมนไม่รู้จักชื่อ Gemini รู้จักแค่ "AiExtractor"

วันหน้าเปลี่ยนไปใช้ AI เจ้าอื่น: เขียน client ใหม่ให้ตรงสัญญานี้ ชั้นธุรกิจไม่ต้องแก้

★ หน้าที่เดียว: อ่านข้อความ OCR แล้วเดา field ที่ระบบต้องการ
  ใช้เป็น "ตัวสำรอง" ตอนกฎของเราอ่านไม่ได้ ไม่ใช่ตัวหลัก
  ผลลัพธ์ห้ามเชื่อตรงๆ — ต้องผ่าน template_rules ก่อน (CONTEXT ข้อ 3)

★ คืน dataclass ของเรา ไม่ใช่ JSON ดิบของ AI — เหตุผลเดียวกับ CrmPort:
  ไม่ให้รูปร่างคำตอบของ vendor รั่วไปทั่วระบบ
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class AiReceiptFields:
    """สิ่งที่ AI เดาได้จากใบเสร็จ — ทุก field เป็น optional เพราะ AI อาจอ่านไม่ครบ

    ★ ค่าเหล่านี้คือ "ข้อเสนอ" ยังไม่ใช่ความจริง — ต้องผ่าน template_rules ก่อน
    """

    total_amount: float | None = None
    receipt_date: date | None = None
    merchant_name: str | None = None
    #: ความมั่นใจที่ AI บอกเอง 0-1 (ถ้าโมเดลให้มา) — ใช้ประกอบ ไม่ใช่ตัวตัดสินเดียว
    confidence: float | None = None


class AiExtractorPort(ABC):
    @abstractmethod
    def extract_fields(self, receipt_text: str) -> AiReceiptFields:
        """อ่านข้อความใบเสร็จ (ที่ผ่าน prompt_guard แล้ว) → field ที่เดาได้

        receipt_text ต้องเป็นข้อความที่ sanitize แล้วเสมอ — ผู้เรียกมีหน้าที่ล้างก่อน
        (สัญญานี้ไม่ล้างเอง เพื่อให้ชัดว่าใครรับผิดชอบการล้าง = ชั้นที่ประกอบ prompt)
        """
        raise NotImplementedError
