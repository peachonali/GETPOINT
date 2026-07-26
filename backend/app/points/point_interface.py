"""สัญญา (Port) ของตัวคำนวณ/ส่งแต้ม — ทำให้แบบ A และ B สลับกันได้"""
from abc import ABC, abstractmethod


class PointStrategy(ABC):
    @abstractmethod
    def send(self, receipt, member) -> dict:
        """ส่งแต้มให้ลูกค้า → คืนผล (เช่น แต้มที่ได้ + แต้มรวม)"""
        raise NotImplementedError
