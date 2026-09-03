"""สัญญา (Port) ของการแจ้งเตือนลูกค้า — โดเมนไม่รู้จักชื่อ LINE

worker เรียกผ่านสัญญานี้ จึงเทสได้โดยไม่ยิง LINE จริง และวันหน้าถ้าเพิ่มช่องทาง
(อีเมล/SMS/แอปอื่น) ก็เขียน implementation ใหม่โดยไม่แตะ scan_job
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class NotifierPort(ABC):
    @abstractmethod
    def notify(self, user_id: str, message: str) -> None:
        """ส่งข้อความหาลูกค้า · ส่งไม่สำเร็จให้ raise ExternalServiceError

        user_id คือรหัสผู้ใช้ในช่องทางนั้น (ของ LINE = lineUserId)
        """
        raise NotImplementedError
