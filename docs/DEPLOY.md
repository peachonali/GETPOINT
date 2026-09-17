# เอาเครื่องมืออ่านใบเสร็จขึ้นใช้งานจริง (สแกนจากมือถือผ่าน LINE)

เป้าหมาย: กดปุ่มใน LINE → เปิดหน้าเว็บ → ถ่าย/เลือกใบเสร็จ → OCR อ่าน → โหลด Excel

มี **2 ทาง** เลือกตามความต้องการ:

| ทาง | เหมาะกับ | ค่าใช้จ่าย | เครื่องต้องเปิดค้าง |
|---|---|---|---|
| **A · Cloudflare Tunnel** | ป้อนรูปฝึก OCR ช่วงนี้ (เริ่มวันนี้เลย) | ฟรี | ✅ ใช่ (PC คุณ) |
| **B · Fly.io** | ใช้งานจริง 24/7 | ~$5-10/เดือน | ❌ ไม่ต้อง |

> แนะนำ: **เริ่มทาง A ก่อน** — ได้ลิงก์ใช้กับ LINE ภายใน 10 นาที ไม่ต้องสมัคร cloud
> พอ OCR แม่นพอใจแล้วค่อยย้ายไปทาง B ให้รัน 24/7

---

## ทาง A — Cloudflare Tunnel (เริ่มวันนี้)

### A1. เปิดเครื่องมือในเครื่องคุณ (terminal ที่ 1)
```powershell
cd C:\Users\ASUS\Desktop\getpoint\backend
python -m uvicorn app.tools.ocr_tool_api:app --host 0.0.0.0 --port 8100
```
รอจนเห็น `อุ่นโมเดล OCR เสร็จ พร้อมรับงาน`

### A2. ติดตั้ง cloudflared (ครั้งเดียว)
- โหลด: https://github.com/cloudflare/cloudflared/releases/latest → ไฟล์ `cloudflared-windows-amd64.exe`
- เปลี่ยนชื่อเป็น `cloudflared.exe` วางไว้ที่ไหนก็ได้ที่จำได้ (เช่น `C:\Users\ASUS\cloudflared.exe`)

### A3. เปิด tunnel (terminal ที่ 2)
```powershell
C:\Users\ASUS\cloudflared.exe tunnel --url http://localhost:8100
```
จะได้ลิงก์ **https** แบบนี้ (ก๊อปเก็บไว้):
```
https://xxxx-yyyy-zzzz.trycloudflare.com
```
> ⚠ ลิงก์นี้เปลี่ยนทุกครั้งที่เปิด tunnel ใหม่ — ต่ออายุ/ลิงก์คงที่ทำได้ถ้ามีโดเมน (บอกผมถ้าจะทำ)

### A4. ทดสอบ
เปิดลิงก์ในมือถือ → ถ่ายใบเสร็จ → กด "อ่านใบเสร็จ" → เห็นผล → โหลด Excel
เอาลิงก์นี้ไปใส่ LINE rich menu (ดูหัวข้อ "ตั้ง LINE rich menu" ด้านล่าง)

---

## ทาง B — Fly.io (24/7)

### B0. ต้องเตรียม (คุณทำ — บอกผมถ้าติด)
1. สมัคร Fly.io: https://fly.io/app/sign-up (ต้องผูกบัตร — คิดเงินตามใช้จริง ~$5-10/เดือน)
2. ติดตั้ง flyctl: เปิด PowerShell แล้วรัน
   ```powershell
   pwsh -Command "iwr https://fly.io/install.ps1 -useb | iex"
   ```
3. ล็อกอิน: `fly auth login`

### B1. ตั้งชื่อ app (แก้ใน `fly.toml`)
เปิด `fly.toml` แก้บรรทัด `app = "getpoint-ocr-CHANGE-ME"` เป็นชื่อที่ไม่ซ้ำใคร
เช่น `app = "getpoint-ocr-vclub"`

### B2. deploy (รันจาก repo root)
```powershell
cd C:\Users\ASUS\Desktop\getpoint
fly launch --no-deploy --copy-config --name getpoint-ocr-vclub   # ครั้งแรกครั้งเดียว
fly deploy
```
ครั้งแรกช้า (~10-15 นาที เพราะ build โมเดลลง image) · ครั้งต่อไปเร็ว

### B3. ได้ลิงก์
```
https://getpoint-ocr-vclub.fly.dev
```
ลิงก์นี้ **คงที่** — เอาไปใส่ LINE rich menu ได้เลย ไม่เปลี่ยน

> ถ้าเจอ error ตอน deploy (เช่น out of memory ตอน build) → ก๊อป error มาให้ผม บอกวิธีแก้ให้

---

## ตั้ง LINE rich menu (ใช้กับทั้ง 2 ทาง)

พอมีลิงก์ https แล้ว:

1. เข้า **LINE Official Account Manager**: https://manager.line.biz/
2. เลือก OA ของคุณ → เมนู **"ริชเมนู" (Rich menu)** ทางซ้าย
3. กด **"สร้างริชเมนู"**
4. ตั้งชื่อ + ช่วงเวลาแสดง
5. เลือกเทมเพลต (เช่นปุ่มเดียวเต็มจอ) → อัปโหลดรูปพื้นหลังปุ่ม
6. ที่ปุ่ม → เลือกการกระทำ **"ลิงก์" (Link)** → วางลิงก์ https ที่ได้
7. บันทึก + เปิดใช้งาน

เสร็จแล้ว: ลูกค้า/คุณกดปุ่มใน LINE → เปิดเว็บ OCR → ถ่ายใบเสร็จ → ได้ผล + Excel

> ⚠ LINE บังคับ **https เท่านั้น** — ทั้ง 2 ทางเป็น https อยู่แล้ว ใช้ได้

---

## ข้อจำกัดที่ต้องรู้ (ตรงไปตรงมา)

- ทาง A: PC ต้องเปิดค้าง + เน็ตบ้านต้องไม่ดับ · ลิงก์เปลี่ยนทุกครั้งที่เปิด tunnel ใหม่
- ทาง B: เสียเงินรายเดือน · ครั้งแรก build นาน (โมเดลหนัก)
- ทั้งคู่: OCR ~8 วิ/ใบ (ครั้งแรกหลังบูตอาจ ~20 วิ ถ้ายังอุ่นโมเดลไม่เสร็จ)
- เครื่องมือนี้ **ยังไม่เก็บรูป/ผลไว้ที่ server** — โหลด Excel เก็บเองทุกครั้ง
  (ถ้าอยากให้เก็บสะสมอัตโนมัติเพื่อทำเฉลย บอกผม เพิ่มให้ได้)
