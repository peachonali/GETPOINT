# CONTEXT — อ่านไฟล์นี้ก่อนเริ่มงาน (สำหรับ Claude Code)

> ไฟล์นี้สรุปบริบททั้งหมดที่ตกลงกันไว้ในเฟสออกแบบ เพื่อให้เข้าใจโปรเจกต์ได้ทันที
> **ลำดับการอ่าน:** ไฟล์นี้ → `GETPOINT_blueprint_v3.md` → `docs/decisions/` → `docs/Loga_API_Document.txt`

---

## 1. โปรเจกต์นี้คืออะไร

**GETPOINT** = middleware ที่ให้ลูกค้าสแกนใบเสร็จผ่าน LINE แล้วแปลงยอดเงินเป็นแต้ม ส่งเข้า CRM (loga)

- **V-CLUB** = แบรนด์หน้าบ้านที่ลูกค้าเห็น (ลูกค้ารู้สึกว่าใช้ V-CLUB)
- **GETPOINT (เรา)** = สร้าง LINE OA + LIFF + สแกน + OCR + resolver ทั้งหมด และเป็นตัวกลางเชื่อมเข้า loga
- **loga** = ระบบ CRM สำเร็จรูปที่มีอยู่แล้ว เราเติมฟีเจอร์สแกนใบเสร็จ→แต้มให้

**เส้นทางระบบ:** ลูกค้าแอด LINE → LIFF → (คนใหม่: OTP ยืนยันเบอร์) → สแกนใบเสร็จ → OpenCV เตรียมรูป → PaddleOCR อ่าน → หาว่าร้านอะไร → แปลงเป็นข้อมูลกลาง → ส่งยอดเงินให้ loga คิดแต้ม → LINE Push แจ้งแต้ม

---

## 2. การตัดสินใจที่ล็อกแล้ว (ห้ามเปลี่ยนโดยไม่ถาม user ก่อน)

| เรื่อง | สรุป | เหตุผล (สำคัญ — ช่องแชทเดิมถกกันมาแล้ว) |
|---|---|---|
| **กุญแจเชื่อมลูกค้า** | เบอร์โทร: `lineUserId → เบอร์ → loga cuid` | loga ระบุลูกค้าด้วยเบอร์ (`cuid`) เท่านั้น และ LIFF ไม่ให้เบอร์ → ต้องเก็บ+ยืนยัน OTP เอง |
| **UX สมัคร** | แบบผสม: LINE Login เงียบ → เห็นหน้าสแกน → กั้น OTP ก่อนรับแต้มครั้งแรก | ได้ทั้ง conversion (ไม่กั้นตั้งแต่แรก) และข้อมูลครบ (ทุกคนที่รับแต้มถูก verify) |
| **คิดแต้ม** | **แบบ B**: ส่ง `cost` + `formula_id` ให้ loga คิดเอง เขียนแบบ **swappable** | loga คิดแต้มจากยอดเงินได้เอง → ตัด Point Engine ในเฟสแรก แต่เก็บช่องเสียบแบบ A (เราคิดเอง) ไว้อนาคต ผ่าน `point_interface.py` |
| **API vs Excel** | API เป็นหลัก · Excel เป็น fallback | ไม่ต้องเลือกอย่างเดียว Excel export = disaster recovery ตอน loga ล่ม (ใช้หน้า Import ที่ loga มีอยู่แล้ว) |
| **ภาษา/โครง** | Python + FastAPI, monorepo (frontend TypeScript+React) | OpenCV/PaddleOCR/Gemini เป็นสาย Python · ทีมเล็ก · เริ่มง่ายขยายได้ |
| **รูปแบบทำงาน** | Async job: `POST /scan` ตอบ 202+job_id ทันที → worker ประมวลผล → LINE Push แจ้งผล | สแกนกิน 5-90 วิ ลูกค้ารอไม่ได้ · แก้ scalability + performance + fault tolerance พร้อมกัน |
| **โครงสร้างรัน** | 2 process: `main.py` (web) + `worker.py` (งานหนัก) codebase เดียว | Bulkhead — OCR กิน CPU หนัก ห้ามลาก web tier ตาย (async ช่วยแค่ I/O ไม่ช่วย CPU) |
| **State** | Postgres + Redis (แค่ 2 ตัว) | Redis = คิวงาน + OTP + rate limit + cache · in-memory จะพังตั้งแต่ instance ที่ 2 |
| **Multi-tenant** | ใส่ `tenant_id` ทุกตารางตั้งแต่วันแรก | วันนี้ = คอลัมน์เดียว · วันที่มีลูกค้ารายที่ 2 = ต้อง rewrite ทุก query |

---

## 3. ประเด็นที่ถกกันมาแล้ว (อย่าเสนอซ้ำเหมือนของใหม่)

ช่องแชทเดิมทำ architecture review 2 รอบและ **จงใจตัดของแพงออก** เพื่อไม่ให้ over-engineer:

**❌ ยังไม่ทำในเฟสนี้ (มีเหตุผลแล้ว ห้ามเพิ่มกลับมาโดยไม่ถาม):**
Kafka/SQS, Kubernetes, multi-region, GPU, OpenTelemetry เต็มระบบ, DI container เต็มรูป, RBAC เต็มรูป, read replica, feature flag platform, cell-based
→ เหตุผล: scale จริงเล็กมาก (ประมาณ < 2 RPS แม้ช่วง peak) การออกแบบเผื่อ 5,000 RPS = ค่า infra หลักแสน/เดือน เพื่องานที่เครื่องเดียวก็เหลือ

**✅ ตั้งใจทำแม้ scale เล็ก (เพราะเป็น latency/correctness ไม่ใช่ throughput):**
async job, แยก web/worker, Redis สำหรับ OTP+rate limit, circuit breaker + timeout + retry(backoff+jitter), tenant_id, interface ที่จุดเปลี่ยนบ่อย, golden test set, ADR

**เรื่องความปลอดภัยที่ระบุไว้แล้ว (อย่ามองข้าม):**
- token loga อยู่ `external/loga_client.py` ฝั่ง backend เท่านั้น — frontend ห้ามแตะ loga ตรง
- **prompt injection ผ่านใบเสร็จ** — OCR text ต้องผ่าน `security/prompt_guard.py` ก่อนเข้า Gemini และห้ามเชื่อผล AI โดยไม่ผ่าน `merchant/template_rules.py`
- OTP เก็บแบบ hash (ไม่ใช่ตัวเลขดิบ), upload check ด้วย magic bytes + ลบ EXIF, PDPA (เก็บเบอร์+รูป = ข้อมูลส่วนบุคคล)
- loga API ใช้ MD5 + credential ใน query string (อ่อนโดยตัวมันเอง แก้ที่เขาไม่ได้) → ต้อง: ไม่ log URL เต็ม, HTTPS เสมอ

---

## 4. หัวใจของ Merchant Template (เรื่องที่ถกหนักสุด)

ปัญหา: ถ้า template เพี้ยนหลุดเข้าระบบ = **ลูกค้าทุกคนของร้านนั้นได้แต้มผิด**

วงจร: `CANDIDATE → SHADOW → OFFICIAL → RETIRED` เลื่อนขั้นต้องผ่าน 4 ด่าน:
1. **กฎตรวจค่าอัตโนมัติ** (`template_rules.py`) — ตัวทรงพลังสุดคือ **เช็กคณิตศาสตร์: ยอดย่อย + VAT = ยอดรวม** (โกหกยาก)
2. **ต้องนิ่งจริง** — ผ่านครบทุกใบจาก 5-10 ใบที่ไม่ซ้ำ คนละคนคนละวัน
3. **คนกดอนุมัติ** (`admin/template_review_routes.py`) ก่อนขึ้นเป็น OFFICIAL เสมอ
4. **เฝ้าระวังหลังใช้** — OFFICIAL ที่ error สูง ลดขั้นอัตโนมัติ (ทำภายหลัง)

`template_version.py` = ห้ามทับของเดิม เพื่อย้อนดู/ย้อนกลับได้ (ร้านเปลี่ยนแบบใบเสร็จแน่นอนใน 5 ปี)

---

## 5. ลำดับการเขียน (walking skeleton — ห้ามข้าม)

**หลักคิด:** ต่อเส้นบางๆ ให้ทะลุถึง loga ก่อนด้วย "ของปลอม" แล้วค่อยเปลี่ยนเป็นของจริงทีละชิ้น

- **Step 0** — โครงรันได้: `docker-compose` + `settings` + `db` + `main.py` + `/health` + `logging`
- **Step 1** — ★ **`external/loga_client.py` ก่อนเลย** (ปลด risk ตัวที่คุมไม่ได้ ถ้ามีเซอร์ไพรส์ต้องรู้วันนี้) + `fake_loga.py` + เทส
- **Step 2** — สมาชิก: `member/*` + OTP (hash/Redis) + `member_link.py` + auth
- **Step 3** — ★ **ต่อเส้นทะลุด้วย `fake_ocr.py`** จนแต้มเข้า loga + LINE Push ได้ 1 รอบ (พิสูจน์สถาปัตยกรรม)
- **Step 4** — OpenCV + PaddleOCR จริง + **เริ่มสะสม `tests/fixtures/receipts/` (golden set)**
- **Step 5** — merchant + template lifecycle + Gemini + หน้า admin อนุมัติ
- **Step 6** — circuit breaker + retry + queue + dead letter + Excel fallback + duplicate check
- **Step 7 (ทำเมื่อใกล้เปิดจริง)** — amount/date check, template_monitor, retention, metrics, audit

รายละเอียดเต็มอยู่ใน `GETPOINT_blueprint_v3.md` ส่วนที่ 5

---

## 6. Coding Conventions ที่ตกลงไว้

- **1 ไฟล์ = 1 หน้าที่** ชื่อไฟล์ตรงตัว (เช่น `opencv_crop.py` ทำแค่ crop) — user ให้ความสำคัญมากกับข้อนี้ ต้องอ่านชื่อแล้วรู้ทันทีว่าทำอะไร
- **ชื่อไฟล์ภาษาอังกฤษ** (กัน import พัง) · **docstring/คอมเมนต์อธิบายเป็นภาษาไทย**
- **โดเมนไม่รู้จักชื่อ vendor** — ใช้ `crm_interface.py`/`CrmPort` ไม่ใช่ชื่อ loga ในชั้นธุรกิจ (`points/crm_formula_strategy.py` ไม่ใช่ `loga_formula.py`)
- **Dependency rule:** `routes → stages → ports` ห้ามย้อน · frontend คุยแต่ backend เรา
- **ทุก external call** ต้องมี timeout + ผ่าน circuit breaker
- **secret จาก env เท่านั้น** (`config/settings.py`) ห้าม hardcode · log ต้อง mask secret
- ไฟล์ interface เขียน abstract class จริงแล้ว → implement ให้ตรงสัญญา

---

## 7. สไตล์การทำงานที่ user ต้องการ (สำคัญ)

- **user เป็น BA/PM ที่มีพื้นเทคนิค แต่ต้องการเข้าใจทุกอย่างที่เขียน** ไม่ใช่แค่ให้โค้ดเสร็จ
- เขียนโค้ด**ทีละไฟล์** ไม่ใช่ทีเดียวหมด — user บอกเองว่า "เขียนทั้งหมดรอบเดียวคงไม่ดี"
- **อธิบายให้เข้าใจไปด้วยทุกไฟล์** ว่าไฟล์นี้ทำอะไร ทำไมเขียนแบบนี้
- ถ้าจะเสนออะไรที่ต่างจากที่ตกลงไว้ (ข้อ 2-3) **ให้ถาม user ก่อน** อย่าเปลี่ยนเงียบๆ
- user ชอบให้เตือนเมื่อมองว่าอะไร over-engineer หรือเกินจำเป็น — ให้ตรงไปตรงมา อย่าเออออ

---

## 8. โครงสร้างไฟล์ปัจจุบัน

ดูโครงเต็มใน `GETPOINT_blueprint_v3.md` ส่วนที่ 4

### ★ สถานะปัจจุบัน → อ่าน `STATE.md`

> **ไฟล์นี้ (CONTEXT) บอก "โปรเจกต์คืออะไร + ตกลงอะไรกันไว้" ซึ่งไม่เปลี่ยน**
> **ส่วน "ตอนนี้ทำถึงไหน / ทำอะไรต่อ" อยู่ใน [`STATE.md`](STATE.md) ซึ่งอัปเดตเรื่อยๆ**
>
> ลำดับการอ่านสำหรับแชทใหม่: **`STATE.md`** → ไฟล์นี้ → blueprint → `docs/decisions/`

สรุปสั้นๆ: Step 0-4 เสร็จแล้ว (โครงรัน, ต่อ loga, สมาชิก+OTP, ต่อเส้นสแกน→แต้ม, OCR จริง)
ถัดไปคือกันใบซ้ำด้วยเลขอ้างอิง แล้วต่อด้วย Step 5 (merchant + template)

---

## 9. มาตรฐานคุณภาพโค้ด (12 ด้าน) — เขียนโดยเล็งเป้าพวกนี้ตั้งแต่แรก

ทุกไฟล์ที่เขียนต้องได้มาตรฐานนี้ **ตั้งแต่ตอนเขียน** ไม่ใช่เขียนมั่วแล้วมาแก้ทีหลัง
(ตัวเลข/แนวทางปรับตามบริบทระบบ scale เล็กที่ออกแบบให้ขยายได้ — ดูข้อ 3 ประกอบ)

1. **Readability** — โค้ดอ่านเข้าใจได้โดยไม่ต้องถาม · ฟังก์ชันสั้น · เลี่ยง nesting ลึก · คอมเมนต์อธิบาย "ทำไม" ภาษาไทยได้
2. **Naming Convention** — ชื่อตรงตัวตามหน้าที่ (user ให้ความสำคัญมาก) · ไฟล์/ฟังก์ชัน/ตัวแปรสื่อความหมาย · โดเมนไม่ใช้ชื่อ vendor (ใช้ CRM ไม่ใช่ loga)
3. **Clean Code** — 1 ไฟล์/1 ฟังก์ชัน = 1 หน้าที่ · ไม่มี dead code · ไม่ซ้ำซ้อน (DRY) · magic number/string เป็นค่าคงที่มีชื่อ
4. **SOLID** — โดยเฉพาะ S (หน้าที่เดียว) และ D (พึ่งพา interface ไม่ใช่ implementation — เรามี Port อยู่แล้ว: CrmPort/OcrEngine/PointStrategy/StoragePort/QueuePort ให้ implement ตาม)
5. **Design Patterns** — ใช้ที่จำเป็นเท่านั้น ไม่ยัด pattern เกิน · ที่ตกลงไว้: Strategy (points A/B), Ports & Adapters (external), Pipeline (image_prep, scan_job)
6. **Error Handling** — ทุก external call (loga/gemini/sms) มี try/except + timeout · error มีความหมาย ไม่กลืนเงียบ · ผ่าน `reliability/errors.py` · ไม่ leak ข้อมูลภายในสู่ลูกค้า
7. **Logging** — ใช้ `observability/logging.py` · **mask secret ทุกครั้ง** (token/password/เบอร์) · ผูก receipt_id/job_id ทุกบรรทัด เพื่อ trace ข้ามด่านได้ · ไม่ log query string เต็มของ loga
8. **Dependency Injection** — ใช้ FastAPI `Depends()` · **ห้ามสร้าง client/connection ข้างในฟังก์ชัน** (เช่นห้าม `loga_client()` กลางฟังก์ชัน) เพื่อให้เทสสลับ fake ได้ · ยังไม่ต้องใช้ DI container เต็มรูป
9. **Testability** — ทุก logic เทสได้โดยไม่ยิงของจริง · ใช้ `fake_loga.py`/`fake_ocr.py` · แยก I/O ออกจาก logic · golden set ใน `tests/fixtures/receipts/`
10. **Performance** — งานหนัก (OCR/Gemini) อยู่ใน worker ไม่ใช่ web · ย่อรูปก่อน OCR · cache template/merchant config/token ใน Redis · เป้า: API < 500ms, งานสแกน < 15s (ดู `docs/slo.md`) · **ยังไม่ต้อง Kafka/GPU** (ดูข้อ 3)
11. **Security** — ดูข้อ 3 (token ฝั่ง backend, prompt_guard ก่อน AI, ไม่เชื่อ AI โดยไม่ผ่าน template_rules, OTP hash, upload check, PDPA) · validate input ทุกอย่างจากลูกค้า
12. **Maintainability** — เขียน ADR ใน `docs/decisions/` ทุกครั้งที่ตัดสินใจสำคัญ · มี migration ทุกครั้งที่แก้ตาราง · docstring บอกหน้าที่/รับ/ส่ง

---

## 10. วิธีสั่ง Review (พร้อม prompt เต็ม)

เมื่อเขียนโค้ดเสร็จเป็นชุด (เช่นจบ 1 Step หรือหลายไฟล์) ให้สั่ง review ด้วย prompt นี้ — ก๊อปไปวางได้เลย:

> **บทบาทของคุณคือ Principal Software Engineer ช่วย Review Source Code นี้ในระดับ Enterprise**
>
> **ก่อน review ให้อ่าน `CONTEXT_for_claude_code.md` ก่อน โดยเฉพาะข้อ 3 (ของที่จงใจตัดออกเพราะ over-engineer) และข้อ 9 (มาตรฐานคุณภาพ 12 ด้าน) — อย่าแนะนำให้เพิ่ม Kafka/K8s/DI container เต็มรูป/RBAC เต็มรูป เพราะเราตัดสินใจไม่ทำในเฟสนี้แล้วด้วยเหตุผล ให้ review ในกรอบของระบบ scale เล็กที่ออกแบบให้ขยายได้ ไม่ใช่ระบบ 5,000 RPS**
>
> ประเมินตามหัวข้อต่อไปนี้: 1. Readability 2. Naming Convention 3. Clean Code 4. SOLID Principles 5. Design Patterns 6. Error Handling 7. Logging 8. Dependency Injection 9. Testability 10. Performance 11. Security 12. Maintainability
>
> สำหรับแต่ละหัวข้อ ให้ระบุ: คะแนนเต็ม 10 · จุดแข็ง · จุดที่ควรปรับปรุง · ตัวอย่างโค้ดที่ควรแก้ (ชี้ไฟล์/บรรทัด) · แนวทางตาม Best Practice
>
> รีวิวเฉพาะโค้ดที่เขียนไปแล้วจริง อย่าหักคะแนนไฟล์ที่ยังเป็น stub (ยังไม่ถึงคิวเขียน)

**เคล็ดลับ:** สั่ง review **ทุกครั้งที่จบ 1 Step** ไม่ต้องรอจบทั้งโปรเจกต์ — เจอปัญหาเร็ว แก้ถูกที่ และมาตรฐาน (ข้อ 9) กับเกณฑ์ตรวจ (ข้อ 10) เป็นชุดเดียวกัน จะได้สอดคล้อง
