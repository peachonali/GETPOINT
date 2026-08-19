"""เลือกกลยุทธ์แต้มที่จะใช้กับใบเสร็จใบนี้

ตอนนี้มีกลยุทธ์เดียว (แบบ B) จึงคืนตัวเดิมเสมอ — แต่ยังต้องมีไฟล์นี้เพราะ
มันคือ "จุดที่การตัดสินใจจะเกิด" เมื่อถึง Step 5 (ตั้งค่า A/B ต่อร้านในตาราง merchants)
พอถึงตอนนั้น scan_job ไม่ต้องแก้เลย เพราะเรียกผ่าน service นี้อยู่แล้ว

⚠ จงใจไม่ใส่ตรรกะ "ถ้าร้าน X ใช้แบบ A" ไว้ล่วงหน้า — ยังไม่มีข้อมูลร้านให้ตัดสิน
  เขียนไปตอนนี้ = เดาอนาคต (blueprint ส่วนที่ 0)
"""
from __future__ import annotations

from app.points.point_interface import PointStrategy
from app.receipt_data.receipt_schema import Receipt


class PointService:
    def __init__(self, default_strategy: PointStrategy) -> None:
        self._default = default_strategy

    def strategy_for(self, receipt: Receipt) -> PointStrategy:
        """เลือกกลยุทธ์ตามใบเสร็จ (วันนี้: ตัวเดียวกันหมด)"""
        return self._default
