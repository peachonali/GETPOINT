"""โครงข้อมูลผลลัพธ์ OCR + รวมชิ้นส่วนกลับเป็น "บรรทัด" ที่คนอ่านเห็น"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TextBox:
    text: str
    bbox: tuple  # (x1, y1, x2, y2)

    @property
    def center_y(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2

    @property
    def height(self) -> float:
        return max(self.bbox[3] - self.bbox[1], 1)


@dataclass
class OcrResult:
    boxes: list[TextBox] = field(default_factory=list)

    def lines(self) -> list[str]:
        """รวมกล่องข้อความที่อยู่ "แถวเดียวกัน" กลับเป็นบรรทัดเดียว

        ★ ทำไมต้องมี: OCR มองเห็นเป็นกล่องๆ ไม่ใช่บรรทัด บรรทัดเดียวบนใบเสร็จ
          มักถูกหั่นเป็นหลายกล่อง เช่น

              "Take Away Total  ฿149.00"
                 ↓ OCR คืนมาเป็น
              ["Tota114900"], ["Take"], ["Away"], ["฿149.00"]

          ถ้าดูทีละกล่องจะไม่มีกล่องไหนที่มีทั้งคำว่า total และยอดเงินอยู่ด้วยกัน
          → หายอดไม่เจอ (เจอจริงกับใบเสร็จ KFC ตอนทดสอบ)

          พอรวมกลับเป็นบรรทัดจะได้ "Take Away Tota114900 ฿149.00" ซึ่งมีครบ
        """
        return [" ".join(box.text for box in row) for row in self._rows()]

    def _rows(self) -> list[list[TextBox]]:
        """จัดกล่องเข้าแถวตามการเหลื่อมกันแนวตั้ง แล้วเรียงในแถวจากซ้ายไปขวา"""
        if not self.boxes:
            return []

        ordered = sorted(self.boxes, key=lambda box: box.center_y)
        rows: list[list[TextBox]] = [[ordered[0]]]

        for box in ordered[1:]:
            # ★ เทียบกับ "กล่องแรกของแถว" (ตัวตั้งต้น) ไม่ใช่กล่องล่าสุด
            #   ถ้าเทียบกับตัวล่าสุด กล่องจะต่อกันเป็นลูกโซ่ทีละนิดจนรวมกันทั้งใบ
            #   (เจอจริง: ชื่อร้านกลายเป็น 5 บรรทัดต่อกันบนใบเสร็จที่ถ่ายเอียง)
            if _same_row(rows[-1][0], box):
                rows[-1].append(box)
            else:
                rows.append([box])

        for row in rows:
            row.sort(key=lambda box: box.bbox[0])
        return rows


#: ต้องเหลื่อมกันแนวตั้งอย่างน้อยเท่านี้ของความสูงตัวที่เตี้ยกว่า ถึงจะนับว่าแถวเดียวกัน
#: 0.5 = ต้องซ้อนกันเกินครึ่ง — เข้มพอไม่ให้คนละบรรทัดมารวมกัน
_SAME_ROW_OVERLAP_RATIO = 0.5


def _same_row(anchor: TextBox, candidate: TextBox) -> bool:
    """อยู่แถวเดียวกันไหม — วัดจากการซ้อนทับกันจริงของกรอบ ไม่ใช่ระยะจุดกึ่งกลาง

    วัดแบบซ้อนทับดีกว่า เพราะตัวอักษรใหญ่-เล็กในแถวเดียวกัน (เช่นยอดรวมตัวโต
    กับป้ายตัวเล็ก) มีจุดกึ่งกลางต่างกันได้มาก แต่กรอบยังซ้อนกันอยู่
    """
    overlap = min(anchor.bbox[3], candidate.bbox[3]) - max(anchor.bbox[1], candidate.bbox[1])
    return overlap >= min(anchor.height, candidate.height) * _SAME_ROW_OVERLAP_RATIO
