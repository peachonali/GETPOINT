"""สัญญา (Port) ของการส่ง SMS — โดเมนไม่รู้จักชื่อผู้ให้บริการ

CONTEXT ข้อ 3 ระบุ sms เป็นจุดที่ควรมี interface (เหมือน CRM) เพราะผู้ให้บริการ SMS
ในไทยมีหลายเจ้าและเปลี่ยนบ่อยตามราคา — วันหน้าเปลี่ยนเจ้า เขียน client ใหม่ให้ตรงสัญญานี้
ชั้น member ไม่ต้องแก้
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class SmsPort(ABC):
    @abstractmethod
    def send_otp(self, phone: str, otp: str) -> None:
        """ส่ง OTP ไปยังเบอร์ · ส่งไม่สำเร็จให้ raise ExternalServiceError

        รับ otp ตรงๆ (ไม่ใช่ข้อความเต็ม) เพราะการจัดรูปข้อความเป็นเรื่องของ client
        แต่ละเจ้า (บางเจ้าต้องมี sender name / template id) — โดเมนไม่ต้องรู้
        """
        raise NotImplementedError
