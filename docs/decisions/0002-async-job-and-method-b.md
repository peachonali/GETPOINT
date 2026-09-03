# 2. ใช้ Async Job + คิดแต้มแบบ B

สถานะ: Accepted

## บริบท
สแกน = OpenCV+OCR(+Gemini) กิน CPU/เวลา 5-90 วิ. loga คิดแต้มจากยอดเงินได้เอง.

## ตัดสินใจ
1. **Async job**: POST /scan ตอบ 202 + job_id ทันที, worker ประมวลผล, แจ้งผลผ่าน LINE Push.
2. **แบบ B**: ส่ง cost + formula_id ให้ loga คิดแต้ม (เขียนแบบ swappable เผื่อแบบ A อนาคต).

## ผล
ลูกค้าไม่รอค้าง, web ไม่ถูก OCR ลากตาย, ตัด Point Engine ในเฟสแรก.
