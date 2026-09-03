# 4. ใช้ SQLAlchemy แบบ sync (ไม่ใช่ async)

สถานะ: Accepted

## บริบท
FastAPI รองรับทั้ง sync และ async · ต้องเลือกก่อนเขียน db.py + ทุก repository

## ตัดสินใจ
ใช้ **sync SQLAlchemy 2.0** — route แบบ sync รันใน threadpool ของ FastAPI

## เหตุผล
- **scale เล็ก** (< 2 RPS): async ช่วยเรื่อง I/O concurrency ต่อ instance ซึ่งเราไม่ติด
- **งานหนักอยู่ worker คนละ process แล้ว** (Bulkhead): web แทบไม่รอ I/O นาน
- **ราคาความซับซ้อนของ async สูง**: ต้อง `await` ทุกจุด, stack trace ยาว, ไลบรารีบางตัว
  (เช่น PaddleOCR, OpenCV) เป็น blocking อยู่แล้ว — ผสม async/sync เพิ่มโอกาสพลาด
- ทีมเล็ก: sync debug ง่ายกว่ามาก

## ผล
- `db.py` มี `create_db_engine(url)` แยกออกมา → เทสสร้าง engine SQLite ของตัวเองได้
- **เทส repository ใช้ SQLite in-memory** (ไม่ต้องมี Postgres/docker ตอนรัน unit test)
- **prod ใช้ Postgres** · เลี่ยง type เฉพาะ Postgres (JSONB/ARRAY) ช่วงแรก
  ไม่ให้ SQLite กับ Postgres แตกคอกัน — ถ้าจำเป็นต้องใช้จริงค่อยย้ายเทสตัวนั้นไป Postgres
- migration ด้วย Alembic (target Postgres)

## กลับทิศได้ไหม
ได้ แต่แพง — ถ้าวันหนึ่ง web ติด I/O จริง (วัดจาก SLO) ต้องเปลี่ยน engine เป็น async
+ แก้ repository ทุกตัวให้ `await` · ราคานี้ยอมรับได้เพราะโอกาสเกิดต่ำมากที่ volume นี้
