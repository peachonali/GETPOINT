"""สัญญา (Port) ของ CRM — โดเมนไม่รู้จักชื่อ loga รู้จักแค่คำว่า "CRM"

วันหน้าเปลี่ยน CRM: เขียน client ใหม่ให้ตรงสัญญานี้ ชั้นธุรกิจไม่ต้องแก้แม้แต่บรรทัดเดียว

★ ทำไม card_id กับ uuid (device id) ไม่อยู่ในสัญญานี้
    ทั้งคู่เป็น "ค่าประจำร้าน/ประจำเครื่อง" ที่เหมือนกันทุกครั้งที่ยิง ไม่ใช่ข้อมูลของ
    ธุรกรรมนั้นๆ (ยืนยันจาก Loga API Integration Guidelines — ดู ADR 0003 ข้อ 4-5)
    ถ้าใส่ไว้ในสัญญา ชั้นธุรกิจจะต้องแบกค่าที่ตัวเองไม่ได้ใช้และไม่ควรรู้จักไปทุกที่
    → ค่าพวกนี้อยู่ใน constructor ของ LogaClient (มาจาก settings) แทน

    สิ่งที่อยู่ในสัญญาคือของที่ "เปลี่ยนไปตามแต่ละธุรกรรม" เท่านั้น

★ คืนค่าเป็น dataclass ไม่ใช่ dict ดิบของ loga
    ถ้าคืน dict ชั้นธุรกิจจะต้องเขียน resp["data"]["user_info"]["uid"] ซึ่งเท่ากับ
    ปล่อยให้รูปร่าง JSON ของ loga รั่วไปทั่วระบบ — พอ loga เปลี่ยน field เราต้องไล่แก้
    ทุกไฟล์ ซึ่งเป็นสิ่งที่ Port ตั้งใจจะป้องกันตั้งแต่แรก
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class CrmCustomer:
    """สมาชิกหนึ่งคนในสายตาระบบเรา (ตัดส่วนที่เราไม่ได้ใช้ของ loga ออกหมด)"""

    #: รหัสที่ใช้อ้างถึงสมาชิกคนนี้ตอนให้แต้ม
    #: (loga: uid ของสมาชิกออนไลน์ หรือ "P" + pcard_id ของสมาชิกบัตรพลาสติก)
    customer_id: str
    phone: str
    name: str | None = None
    points_balance: int | None = None


@dataclass(frozen=True)
class PointAwardResult:
    """ผลของการให้แต้ม 1 ครั้ง"""

    #: เลขอ้างอิงที่เราส่งไป (เลขที่ใบเสร็จ) — ยิงซ้ำด้วยค่าเดิม CRM จะไม่บันทึกซ้ำ
    reference: str
    #: แต้มสะสมล่าสุดหลังรายการนี้
    points_balance: int | None = None
    #: แต้มที่ได้จากรายการนี้ — ⚠ loga ไม่ส่งค่านี้กลับมา (คืนแค่ยอดสะสมล่าสุด)
    #: จึงมักเป็น None · ดูหัวข้อ "ยังไม่ตัดสินใจ" ใน ADR 0003
    points_added: int | None = None


class CrmPort(ABC):
    """สิ่งที่ระบบเราต้องการจาก CRM — มีแค่ 3 อย่าง"""

    @abstractmethod
    def find_customer(self, phone: str) -> CrmCustomer | None:
        """หาสมาชิกจากเบอร์โทร · ไม่เจอคืน None (ไม่ใช่โยน error)

        ต้องเรียกก่อน register_customer เสมอ เพราะ loga ไม่อนุญาตให้สมัครซ้ำ
        ด้วยเบอร์ที่มีอยู่ในระบบแล้ว (ADR 0003 ข้อ 6)
        """
        raise NotImplementedError

    @abstractmethod
    def register_customer(self, phone: str, name: str | None = None) -> CrmCustomer:
        """สมัครสมาชิกใหม่ด้วยเบอร์โทร

        ใช้คำว่า register ไม่ใช่ subscribe (คำของ loga) เพราะชั้นธุรกิจควรอ่านแล้ว
        เข้าใจโดยไม่ต้องรู้จักศัพท์ของ vendor
        """
        raise NotImplementedError

    @abstractmethod
    def add_points(
        self,
        *,
        customer_id: str,
        cost: float,
        formula_id: str,
        remark: str,
        reference: str,
    ) -> PointAwardResult:
        """ให้แต้มจากยอดใช้จ่าย (วิธีแบบ B — ให้ CRM คิดแต้มเอง ดู ADR 0002)

        customer_id  รหัสสมาชิกที่ได้จาก find_customer / register_customer
        cost         ยอดเงินบนใบเสร็จ
        formula_id   สูตรคิดแต้มที่ร้านตั้งไว้ใน CRM (เก็บต่อร้านในตาราง merchants)
        remark       ข้อความที่ "ลูกค้าจะเห็น" — ไม่ใช่หมายเหตุภายใน
        reference    เลขที่ใบเสร็จ ใช้กันการให้แต้มซ้ำ (idempotency)
        """
        raise NotImplementedError
