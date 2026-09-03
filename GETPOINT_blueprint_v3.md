# GETPOINT — พิมพ์เขียวฉบับสรุป (v3 — ปรับขนาดให้พอดีแล้ว)

> เอกสารนี้คือ **ฉบับตั้งต้นอันเดียวที่ใช้จริง** รวมทุกอย่างที่ตกลงกันแล้ว
> v1 = โครงแรก · v2 = เติม test/security · **v3 = ตัดของเกินจำเป็นออก + แก้ P0**

---

## ส่วนที่ 0 — ปรัชญาของฉบับนี้: "เผื่อสิ่งที่ถูก"

การคิดเผื่อไม่ใช่เรื่องผิด แต่ต้องแยกให้ออกว่าเผื่ออะไร:

| ประเภท | ราคาถ้าทำวันนี้ | ราคาถ้าทำทีหลัง | ตัดสิน |
|---|---|---|---|
| **สิ่งที่แก้ทีหลังแพงมาก** (โครงสร้าง, tenant_id, async pattern, interface) | เกือบศูนย์ | ต้อง rewrite | ✅ **ทำเลย** |
| **สิ่งที่เพิ่มทีหลังได้ง่าย** (Kafka, K8s, multi-region, GPU) | แพงมาก + ซับซ้อน | เพิ่มได้เมื่อจำเป็น | ❌ **ยังไม่ทำ** |

**หลักคิด:** ออกแบบ *โครงสร้าง* ให้รองรับอนาคต แต่ *ติดตั้ง* เฉพาะที่ต้องใช้วันนี้

---

## ส่วนที่ 1 — สรุปการตัดสินใจทั้งหมด (Decision Log)

| # | เรื่อง | สรุป | เหตุผล |
|---|---|---|---|
| 1 | ใครทำอะไร | GETPOINT สร้าง LINE/LIFF/สแกน/OCR ทั้งหมด · V-CLUB คือแบรนด์หน้าบ้าน · loga คือ CRM ปลายทาง | — |
| 2 | กุญแจเชื่อมลูกค้า | **เบอร์โทร** (`lineUserId` → เบอร์ → loga `cuid`) | loga ไม่รู้จัก lineUserId, LIFF ไม่ให้เบอร์ → ต้อง OTP เอง |
| 3 | UX สมัคร | **แบบผสม** — LINE Login เงียบ → เห็นหน้าสแกนได้ → กั้น OTP ก่อนรับแต้มครั้งแรก | ได้ทั้ง conversion และข้อมูลครบ |
| 4 | คิดแต้ม | **แบบ B** (ส่ง `cost` + `formula_id` ให้ loga คิด) แต่เขียนแบบ **สลับได้** | ตัด Point Engine ทิ้งวันนี้ เปิดทางแบบ A อนาคต |
| 5 | API vs Excel | **API หลัก · Excel เป็น fallback** | ไม่ต้องเลือกอย่างเดียว Excel = disaster recovery ฟรี |
| 6 | ภาษา/โครง | **Python + FastAPI, monorepo** (frontend TS) | OCR/CV/AI เป็นสาย Python · ทีมเล็ก |
| 7 | 🆕 **รูปแบบการทำงาน** | **Async job** — ตอบ 202 ทันที แล้วแจ้งผลผ่าน LINE Push | ลูกค้าไม่ต้องรอ 20 วิ (แก้ P0 #1) |
| 8 | 🆕 **โครงสร้างรัน** | **2 process: web + worker** อยู่ใน codebase เดียว | Bulkhead — OCR ระเบิดไม่ลาก web ตาย |
| 9 | 🆕 **ที่เก็บ state** | **Postgres + Redis** (แค่ 2 ตัว) | Redis = คิวงาน + OTP + rate limit + cache |
| 10 | 🆕 **Multi-tenant** | ใส่ `tenant_id` ทุกตารางตั้งแต่วันแรก | วันนี้ฟรี · วันที่มีลูกค้ารายที่ 2 = rewrite |

---

## ส่วนที่ 2 — 🔴 การเปลี่ยนแปลงใหญ่ที่สุดใน v3: Async Job

### ปัญหาของ v2
```
กดส่ง → OpenCV(1-3s) → OCR(2-8s) → [ร้านใหม่: Gemini 10-60s] → loga(1-3s) → ตอบ
รวม 5-20 วิ (ปกติ) / 30-90 วิ (ร้านใหม่)
→ ลูกค้าคิดว่าค้าง กดซ้ำ → โหลด 2 เท่า → แย่ลงอีก
```

### ทางแก้ใน v3
```
[LIFF] --POST /scan--> [web] --เก็บรูป + โยนเข้าคิว--> ตอบ 202 + job_id  (< 500ms)
                                      ↓
                          ลูกค้าเห็น "กำลังประมวลผล..." ปิดแอปได้เลย
                                      ↓
[worker] ดึงงาน → OpenCV → OCR → merchant → JSON → check → ส่ง loga
                                      ↓
                    LINE Push: "คุณได้รับ 25 แต้ม 🎉"
```

**ทำไมนี่คือการแก้ที่คุ้มที่สุด:**
- แก้ปัญหา 3 ด้านพร้อมกัน (Scalability 5→8, Performance 4→8, Fault Tolerance 6→8)
- **ไม่เกี่ยวกับจำนวนผู้ใช้เลย** — รอ 20 วิมันแย่ตั้งแต่ผู้ใช้คนแรก
- LINE Push ให้ UX **ดีกว่า** การนั่งรอด้วยซ้ำ — ปิดแอปไปทำอย่างอื่นได้
- ราคาถูก: แค่แยก process ไม่ต้องซื้ออะไรเพิ่ม

---

## ส่วนที่ 3 — ✅ ทำอะไร / ❌ ยังไม่ทำ (สำคัญ — กัน over-engineering)

### ✅ ทำตอนนี้ (ราคาถูก + แก้ทีหลังแพง)
| ทำ | เพราะ |
|---|---|
| Async job + LINE Push | latency problem ไม่ใช่ scale problem — แย่ตั้งแต่คนแรก |
| แยก web / worker process | Bulkhead — แค่แยก process ไม่มีค่าใช้จ่ายเพิ่ม |
| Redis (คิว + OTP + rate limit + cache) | **in-memory พังตั้งแต่ instance ที่ 2** ซึ่งต้องมีเพื่อ availability |
| Timeout + retry w/ jitter + circuit breaker | loga ล่มตอนมีคนใช้ 10 คนก็พังเหมือนกัน · เขียนครั้งเดียวจบ |
| `tenant_id` ทุกตาราง | วันนี้ = คอลัมน์เดียว · วันหน้า = แก้ทุก query ทุก index |
| Interface ที่จุดเปลี่ยนบ่อย (OCR, points, storage, queue, sms) | เพิ่มทีหลัง = รื้อ |
| golden set (`tests/fixtures/receipts/`) | สะสมตั้งแต่วันแรก ยิ่งนานยิ่งมีค่า |
| ADR (`docs/decisions/`) | อีก 3 ปีจะลืมว่าทำไมเลือกแบบ B |
| Template lifecycle + human approval | template เพี้ยน = ลูกค้าทั้งร้านได้แต้มผิด |
| OTP แบบ hash + upload check + prompt guard | ความปลอดภัยพื้นฐาน ราคาถูก |

### ❌ ยังไม่ทำ (แพง + เพิ่มทีหลังได้)
| ไม่ทำ | เพราะ | ทำเมื่อไหร่ |
|---|---|---|
| **Kafka / SQS** | Redis queue พอเหลือเฟือ | > 50 ใบ/นาที ต่อเนื่อง |
| **Kubernetes** | docker-compose บน VPS เดียวพอ | มี > 5 service หรือทีม > 10 คน |
| **Multi-region / cell-based** | ลูกค้าอยู่ไทยหมด | มีลูกค้าต่างประเทศ |
| **GPU สำหรับ OCR** | CPU พอที่ volume นี้ | OCR ช้ากว่า 10 วิ ต่อเนื่อง |
| **OpenTelemetry เต็มระบบ** | log แบบมี `receipt_id` ก็ debug ได้ | มี > 3 service |
| **Service mesh / DI container เต็มรูป** | FastAPI `Depends()` พอ | ทีมโตขึ้นมาก |
| **RBAC เต็มรูป + SSO** | role แบบง่าย (admin/reviewer) พอ | ทีมหลังบ้าน > 10 คน |
| **Read replica / sharding** | Postgres เดียวรับได้ล้นเหลือ | DB CPU > 70% ต่อเนื่อง |
| **Feature flag platform** | flag ในตาราง DB พอ | ปล่อยของถี่มาก |

### ประมาณการค่าใช้จ่าย (ช่วงเริ่มต้น)
| รายการ | ราคา/เดือน |
|---|---|
| VPS (web + worker + Postgres + Redis ผ่าน docker-compose) | ~700–2,000 ฿ |
| SMS OTP | ~0.20 ฿ × คนสมัครใหม่ |
| Gemini (เฉพาะร้านใหม่) | ไม่กี่บาท |
| Storage รูป | หลักสิบบาท |
| LINE OA (ถ้ายังไม่ broadcast) | **ฟรี** |
| **รวม** | **~1,000–3,000 ฿/เดือน** |

> เทียบ: ถ้าออกแบบเผื่อ 5,000 RPS → Kafka + K8s + multi-region + GPU = **หลักแสนบาท/เดือน** เพื่อรองรับงานที่เครื่องเดียวก็เหลือ

---

## ส่วนที่ 4 — โครงสร้างสุดท้าย (v3)

> 🆕 = เพิ่ม/เปลี่ยนใน v3 · ⏸ = สร้างไฟล์เปล่าไว้ก่อน ยังไม่เขียน

```
getpoint/
│
├── frontend/                              # ═══ LIFF (TypeScript + React) ═══
│   ├── src/
│   │   ├── liff-init.ts                   # เปิด LIFF + LINE Login เงียบ → lineUserId
│   │   ├── config.ts                      # ค่าสาธารณะเท่านั้น (ห้ามมี secret)
│   │   ├── screens/
│   │   │   ├── RegisterScreen.tsx         #   กรอกเบอร์ + OTP
│   │   │   ├── ScanScreen.tsx             #   กล้อง / อัปโหลด
│   │   │   ├── ProcessingScreen.tsx       # 🆕 "กำลังประมวลผล..." (เพราะ async แล้ว)
│   │   │   └── ResultScreen.tsx           #   แสดงแต้ม
│   │   ├── components/
│   │   │   ├── CameraCapture.tsx          #   เปิดกล้อง/เลือกรูป
│   │   │   ├── ImageResizer.ts            # 🆕 ย่อรูปก่อนอัปโหลด (~1600px) — เร็วขึ้นมาก
│   │   │   ├── OtpInput.tsx               #   ช่องกรอก OTP
│   │   │   └── PointCard.tsx              #   การ์ดโชว์แต้ม
│   │   └── api/
│   │       ├── generated-types.ts         # 🆕 ★ สร้างอัตโนมัติจาก backend (ไม่แก้มือ)
│   │       ├── auth-api.ts                #   สมัคร/OTP
│   │       ├── scan-api.ts                #   ส่งรูป → ได้ job_id
│   │       ├── job-api.ts                 # 🆕 ถามสถานะงาน
│   │       └── point-api.ts               #   ขอ/แสดงแต้ม
│   ├── tests/
│   ├── package.json
│   └── tsconfig.json
│
├── backend/
│   └── app/
│       ├── main.py                        # ★ ประตู 1: web process (รับ HTTP)
│       ├── worker.py                      # 🆕 ★ ประตู 2: worker process (ทำงานหนัก)
│       │
│       ├── routes/                        # ── ประตูรับ HTTP (บางมาก) ──
│       │   ├── auth_routes.py             #   สมัคร/OTP
│       │   ├── scan_routes.py             # 🆕 รับรูป → เข้าคิว → ตอบ 202 + job_id
│       │   ├── job_routes.py              # 🆕 GET /jobs/{id} — ถามสถานะ
│       │   ├── point_routes.py            #   เรื่องแต้ม
│       │   └── health_routes.py           #   เช็กระบบยังมีชีวิต
│       │
│       ├── jobs/                          # 🆕 ═══ คิวงานสแกน (ภายใน) ═══
│       │   ├── job_queue.py               #   โยนงานเข้า Redis / ดึงงานออก
│       │   ├── job_status.py              #   สถานะงาน (รอ/ทำอยู่/เสร็จ/ล้มเหลว)
│       │   └── scan_job.py                #   ★ ตัวคุมทั้งสาย: CV→OCR→merchant→JSON→check→point
│       │
│       ├── config/                        # 🆕 (แยกจาก common เดิม)
│       │   └── settings.py                #   อ่าน env — ที่เดียวของระบบ
│       │
│       ├── security/                      # 🆕 (แยกจาก common เดิม)
│       │   ├── auth_guard.py              #   ยามลูกค้า: เช็ก LINE token จริง
│       │   ├── admin_guard.py             #   ยามหลังบ้าน (คนละชั้น + role)
│       │   ├── rate_limit.py              # 🆕 ใช้ Redis (ไม่ใช่ memory)
│       │   ├── upload_check.py            #   magic bytes + ขนาด + ลบ EXIF
│       │   └── prompt_guard.py            #   ล้าง OCR text ก่อนเข้า AI
│       │
│       ├── observability/                 # 🆕 (แยกจาก common เดิม)
│       │   ├── logging.py                 #   log + mask secret + ผูก receipt_id ทุกบรรทัด
│       │   ├── metrics.py                 #   นับสแกนสำเร็จ/ล้มเหลว/เวลาที่ใช้
│       │   └── audit_log.py               #   ใครทำอะไรกับแต้ม
│       │
│       ├── reliability/                   # 🆕 (แยกจาก common เดิม)
│       │   ├── circuit_breaker.py         # 🆕 loga/Gemini/SMS ล่ม → ตัดวงจร ไม่ retry ซ้ำเติม
│       │   ├── retry_policy.py            # 🆕 exponential backoff + jitter
│       │   ├── idempotency.py             #   กันกดซ้ำ/ส่งซ้ำ
│       │   └── errors.py                  #   error รวมศูนย์
│       │
│       ├── member/                        # ── ด่าน 2: สมาชิก + ผูก loga ──
│       │   ├── phone_normalize.py         #   แปลงเบอร์ให้รูปแบบเดียว
│       │   ├── otp_generate.py            #   สุ่มรหัส
│       │   ├── otp_store.py               #   เก็บแบบ hash ใน Redis + นับกรอกผิด
│       │   ├── otp_verify.py              #   ตรวจถูก/ไม่หมดอายุ/ไม่เคยใช้
│       │   ├── member_link.py             #   ★ ผูก lineUserId ↔ เบอร์ ↔ loga id
│       │   └── member_service.py          #   ตัวคุมภาพรวม
│       │
│       ├── storage/                       # ── ที่เก็บหลักฐาน ──
│       │   ├── storage_interface.py       # 🆕 สัญญา (วันหน้าย้ายไป S3 ไม่ต้องรื้อ)
│       │   ├── local_storage.py           # 🆕 เก็บบนดิสก์ (ใช้ตอนนี้)
│       │   ├── image_store.py             #   เก็บ/ดึงรูปต้นฉบับ
│       │   └── ocr_text_store.py          #   เก็บข้อความ OCR ดิบ
│       │
│       ├── image_prep/                    # ── ด่าน 3a: OpenCV ──
│       │   ├── opencv_crop.py             #   หาขอบ + ตัดพื้นหลัง
│       │   ├── opencv_deskew.py           #   ดัดภาพเอียง
│       │   ├── opencv_enhance.py          #   contrast + ลด noise
│       │   ├── image_quality.py           #   เบลอเกิน → ตีกลับให้ถ่ายใหม่ (fail fast)
│       │   └── image_pipeline.py          #   สั่ง crop → deskew → enhance
│       │
│       ├── ocr/                           # ── ด่าน 3b: อ่านตัวอักษร ──
│       │   ├── ocr_interface.py           #   สัญญา
│       │   ├── paddle_ocr.py              #   ตัวจริง
│       │   ├── fake_ocr.py                #   ตัวปลอมสำหรับเทส
│       │   └── ocr_result.py              #   โครงผลลัพธ์ (ข้อความ + bbox)
│       │
│       ├── merchant/                      # ── ด่าน 4: ร้าน + template ──
│       │   ├── merchant_resolver.py       #   รู้จักไหม? → known / gemini
│       │   ├── known_merchant.py          #   ใช้ template เดิม
│       │   ├── gemini_resolver.py         #   ร้านใหม่ → AI เสนอ template
│       │   ├── template_matcher.py        #   ดึง field จาก OCR ตาม template
│       │   ├── template_rules.py          #   ★ กฎตรวจค่า (VAT+ยอดย่อย=ยอดรวม ฯลฯ)
│       │   ├── template_candidate.py      #   สะสมสถิติจากหลายใบ
│       │   ├── template_promotion.py      # 🆕 กฎเลื่อนขั้น candidate→official
│       │   ├── template_monitor.py        # 🆕 ⏸ เฝ้าระวัง + ลดขั้น (แยกจาก promotion)
│       │   ├── template_version.py        #   จัดการ v1/v2 + ย้อนกลับ
│       │   ├── template_store.py          #   อ่าน/เขียน template
│       │   └── templates/                 #   แม่แบบร้าน
│       │
│       ├── receipt_data/                  # ── ด่าน 5: ข้อมูลกลาง ──
│       │   ├── receipt_schema.py          # ★ นิยาม field กลาง → export เป็น TS อัตโนมัติ
│       │   ├── receipt_identity.py        # 🆕 hash ใบเสร็จ (ย้ายมาจาก storage — เป็น domain)
│       │   └── field_extractor.py         #   ยัดค่าลงโครงกลาง
│       │
│       ├── receipt_check/                 # ── ด่าน 6: ตรวจใบเสร็จ ──
│       │   ├── duplicate_check.py         #   กันใบซ้ำ
│       │   ├── amount_check.py            #   ⏸ กันยอดผิดปกติ
│       │   ├── date_check.py              #   ⏸ กันใบเก่า
│       │   └── check_pipeline.py          #   สั่งตรวจตามลำดับ
│       │
│       ├── points/                        # ── ด่าน 7: แต้ม (สลับ A/B) ──
│       │   ├── point_interface.py         #   สัญญากลาง
│       │   ├── crm_formula_strategy.py    # 🆕 แบบ B: ให้ CRM คิด (เลี่ยงชื่อ vendor ในโดเมน)
│       │   ├── local_engine.py            #   ⏸ แบบ A: เราคิดเอง (อนาคต)
│       │   └── point_service.py           #   เลือก A/B ตามร้าน
│       │
│       ├── send_queue/                    # ── ด่าน 8: คิวส่งแต้มเข้า loga (ขาออก) ──
│       │   ├── queue_interface.py         # 🆕 สัญญา (วันหน้าเปลี่ยนเป็น SQS ไม่ต้องรื้อ)
│       │   ├── send_queue.py              #   คิว + retry
│       │   ├── dead_letter.py             #   งานที่ส่งไม่สำเร็จจริงๆ ไม่หายไปไหน
│       │   └── excel_export.py            #   ★ fallback ให้คนอัปโหลดเอง
│       │
│       ├── external/                      # ── ระบบภายนอก ──
│       │   ├── crm_interface.py           # 🆕 สัญญา CRM (โดเมนไม่รู้จักชื่อ loga)
│       │   ├── loga_client.py             #   ★ คุยกับ loga ที่เดียว + ขัง token
│       │   ├── loga_token.py              #   login / refresh token
│       │   ├── fake_loga.py               #   loga ปลอมสำหรับเทส
│       │   ├── line_client.py             #   LINE — รวม ★ Push Message แจ้งแต้ม
│       │   ├── gemini_client.py           #   Gemini (เฉพาะร้านใหม่)
│       │   └── sms_client.py              #   ส่ง SMS OTP
│       │
│       ├── database/                      # ── ตาราง (ทุกตารางมี tenant_id) ──
│       │   ├── db.py                      #   เชื่อมต่อ + connection pool
│       │   ├── tenants.py                 # 🆕 แบรนด์/ลูกค้า (วันนี้มีแถวเดียว: V-CLUB)
│       │   ├── members.py                 #   สมาชิก
│       │   ├── receipts.py                #   ประวัติใบเสร็จ + hash + template version ที่ใช้
│       │   ├── merchants.py               #   ร้าน + ตั้งค่าต่อร้าน (A/B, formula_id)
│       │   ├── templates.py               #   แม่แบบ + version + สถานะ
│       │   ├── send_queue.py              #   คิวส่ง
│       │   ├── audit_logs.py              #   บันทึกการกระทำ
│       │   └── migrations/                #   ★ ประวัติการเปลี่ยนตาราง
│       │
│       ├── admin/                         # ── หลังบ้านทีมเรา ──
│       │   ├── template_review_routes.py  #   ★ รีวิว/อนุมัติ template
│       │   ├── queue_admin_routes.py      #   ดูคิวค้าง + ส่งใหม่ + export Excel
│       │   └── merchant_config_routes.py  #   ตั้งค่าต่อร้าน
│       │
│       ├── background/
│       │   └── retention_worker.py        #   ⏸ ลบข้อมูลเก่าตาม PDPA (soft delete + dry-run)
│       │
│       └── requirements.txt
│
├── tests/
│   ├── unit/                              #   เทสทีละไฟล์
│   ├── integration/                       #   หลายด่านต่อกัน (ใช้ fake)
│   ├── e2e/test_scan_to_point.py          #   ★ ทั้งเส้น: สแกน → แต้มเข้า loga ปลอม
│   ├── security/                          #   upload attack, prompt injection, rate limit, secret leak
│   ├── fixtures/receipts/                 #   ★★ golden set — เริ่มสะสมวันแรก
│   ├── fixtures/expected/                 #   คำตอบที่ถูกของแต่ละรูป
│   └── conftest.py
│
├── docs/
│   ├── architecture.md                    #   ภาพรวม + ทำไมออกแบบแบบนี้
│   ├── decisions/                         #   ★ ADR — บันทึกทุกการตัดสินใจสำคัญ
│   ├── template_lifecycle.md              #   วงจร candidate → official
│   ├── slo.md                             # 🆕 เป้าหมาย: API < 500ms · งานสแกนเสร็จ < 15s (p95)
│   ├── threat_model.md                    #   ⏸ STRIDE
│   └── runbook.md                         #   ระบบพังต้องทำอะไร
│
├── .github/workflows/ci.yml               #   รันเทส + gen types อัตโนมัติ
├── docker-compose.yml                     #   web + worker + postgres + redis
├── .env.example
└── README.md
```

### สิ่งที่หายไปจาก v2 (และทำไม)
- `common/` → แตกเป็น `config/` `security/` `observability/` `reliability/` (กัน junk drawer)
- `shared/receipt_contract.md` → **ลบทิ้ง** ใช้ `receipt_schema.py` แล้ว generate TypeScript แทน (สัญญาที่บังคับใช้ได้จริง)
- `storage/receipt_hash.py` → ย้ายไป `receipt_data/receipt_identity.py` (เป็น domain ไม่ใช่ infra)
- `storage/retention.py` → ย้ายไป `background/retention_worker.py` (เป็นนโยบาย ไม่ใช่ storage)
- `points/loga_formula.py` → เปลี่ยนชื่อเป็น `crm_formula_strategy.py` (โดเมนไม่ควรรู้จักชื่อ vendor)
- `send_queue/retry_policy.py` → ย้ายไป `reliability/` (ใช้ร่วมกับทุก external call)

---

## ส่วนที่ 5 — ★ ลำดับการเขียน (ทีละไฟล์)

**หลักคิด: "ต่อเส้นบางๆ ให้ทะลุถึง loga ก่อน แล้วค่อยเปลี่ยนของปลอมเป็นของจริงทีละชิ้น"**
(Walking Skeleton — ใช้ที่ Google/Amazon เพราะได้ feedback เร็วที่สุด)

### 🔹 Step 0 — โครง (ไม่มี logic)
| ลำดับ | ไฟล์ | ทำอะไร |
|---|---|---|
| 1 | `docker-compose.yml` | ยกระบบขึ้นได้ด้วยคำสั่งเดียว |
| 2 | `.env.example` + `config/settings.py` | อ่าน config ที่เดียว |
| 3 | `database/db.py` + `migrations/` แรก | ต่อ DB ได้ |
| 4 | `main.py` + `routes/health_routes.py` | เปิดเว็บได้ + เช็กว่ามีชีวิต |
| 5 | `observability/logging.py` | มี log ที่ mask secret ตั้งแต่แรก |
> **จบ step นี้ = รันขึ้น เปิด `/health` เจอ**

### 🔹 Step 1 — ปลด risk ตัวที่เราคุมไม่ได้ก่อน ★ สำคัญที่สุด
| ลำดับ | ไฟล์ | ทำอะไร |
|---|---|---|
| 6 | `external/crm_interface.py` | สัญญา CRM |
| 7 | `external/loga_token.py` | login + refresh token |
| 8 | `external/loga_client.py` | ★ ยิง loga จริง |
| 9 | `external/fake_loga.py` | loga ปลอมสำหรับเทส |
| 10 | `tests/integration/test_send_to_loga.py` | พิสูจน์ว่าส่งได้จริง |
> **ทำไมก่อน:** loga คือสิ่งเดียวที่เราแก้ไม่ได้ ถ้าตรงนี้มีเซอร์ไพรส์ ต้องรู้ **วันนี้** ไม่ใช่เดือนหน้า

### 🔹 Step 2 — สมาชิก (ถ้าระบุตัวคนไม่ได้ อย่างอื่นไม่มีความหมาย)
| ลำดับ | ไฟล์ |
|---|---|
| 11 | `database/tenants.py` + `members.py` (มี `tenant_id`) |
| 12 | `member/phone_normalize.py` |
| 13 | `member/otp_generate.py` + `otp_store.py` (hash ใน Redis) + `otp_verify.py` |
| 14 | `security/rate_limit.py` (Redis) |
| 15 | `member/member_link.py` ★ + `member_service.py` |
| 16 | `security/auth_guard.py` + `routes/auth_routes.py` |
| 17 | `frontend/liff-init.ts` + `RegisterScreen.tsx` |
> **จบ step นี้ = ลูกค้าจริงสมัครผ่าน LINE แล้วมีตัวตนใน loga ได้**

### 🔹 Step 3 — ★ ต่อเส้นทะลุด้วยของปลอม (จุดสำคัญที่สุดของทั้งโปรเจกต์)
| ลำดับ | ไฟล์ |
|---|---|
| 18 | `receipt_data/receipt_schema.py` + `receipt_identity.py` |
| 19 | `jobs/job_queue.py` + `job_status.py` |
| 20 | `security/upload_check.py` + `storage/` (interface + local + image_store) |
| 21 | `routes/scan_routes.py` (202 + job_id) + `routes/job_routes.py` |
| 22 | `ocr/fake_ocr.py` (คืนค่าคงที่) |
| 23 | `jobs/scan_job.py` ★ (ต่อทุกด่าน แต่ยังใช้ของปลอม) |
| 24 | `worker.py` |
| 25 | `points/point_interface.py` + `crm_formula_strategy.py` + `point_service.py` |
| 26 | `external/line_client.py` (Push Message) |
| 27 | `frontend/ScanScreen.tsx` + `ProcessingScreen.tsx` + `ResultScreen.tsx` |
| 28 | `tests/e2e/test_scan_to_point.py` |
> **จบ step นี้ = สแกน 1 ใบ → แต้มเข้า loga จริง → LINE เด้งแจ้ง**
> **สถาปัตยกรรมทั้งหมดถูกพิสูจน์แล้วว่าใช้ได้ ที่เหลือคือเปลี่ยนของปลอมเป็นของจริง**

### 🔹 Step 4 — ของจริงชิ้นที่ 1: อ่านใบเสร็จ
| ลำดับ | ไฟล์ |
|---|---|
| 29 | `frontend/ImageResizer.ts` (ย่อรูปก่อนส่ง) |
| 30-33 | `image_prep/opencv_crop → deskew → enhance → image_pipeline` |
| 34 | `image_prep/image_quality.py` |
| 35 | `ocr/ocr_interface.py` + `paddle_ocr.py` + `ocr_result.py` |
| 36 | `storage/ocr_text_store.py` |
| 37 | **`tests/fixtures/receipts/` — เริ่มสะสมใบเสร็จจริง** ★★ |
> **จบ step นี้ = อ่านใบเสร็จจริงได้ (แต่ยังรู้จักร้านเดียว)**

### 🔹 Step 5 — ของจริงชิ้นที่ 2: สมองเรื่องร้าน (ยากสุด ทำตอนรอบข้างพร้อมแล้ว)
| ลำดับ | ไฟล์ |
|---|---|
| 38 | `database/merchants.py` + `templates.py` |
| 39 | `merchant/template_store.py` + `template_version.py` |
| 40 | `merchant/template_matcher.py` + `template_rules.py` ★ |
| 41 | `merchant/known_merchant.py` + `merchant_resolver.py` |
| 42 | `security/prompt_guard.py` + `external/gemini_client.py` |
| 43 | `merchant/gemini_resolver.py` + `template_candidate.py` + `template_promotion.py` |
| 44 | `admin/admin_guard.py` + `template_review_routes.py` ★ (คนอนุมัติ) |
> **จบ step นี้ = ร้านใหม่เรียนรู้เองได้ + มีคนคุมก่อนขึ้นเป็นตัวจริง**

### 🔹 Step 6 — ทนล่ม
| ลำดับ | ไฟล์ |
|---|---|
| 45 | `reliability/retry_policy.py` (backoff + jitter) + `circuit_breaker.py` |
| 46 | `send_queue/queue_interface.py` + `send_queue.py` + `dead_letter.py` |
| 47 | `send_queue/excel_export.py` + `admin/queue_admin_routes.py` |
| 48 | `receipt_check/duplicate_check.py` + `check_pipeline.py` |
> **จบ step นี้ = loga ล่มก็ไม่มีแต้มหาย**

### 🔹 Step 7 — เก็บงาน (⏸ ทำเมื่อใกล้เปิดจริง)
`amount_check` · `date_check` · `template_monitor` · `retention_worker` · `audit_log` · `metrics` · `threat_model.md` · `runbook.md`

---

## ส่วนที่ 6 — เกณฑ์ตัดสินว่า "พอแล้ว" (`docs/slo.md`)

| ตัวชี้วัด | เป้าหมาย |
|---|---|
| API `/scan` ตอบกลับ | < 500ms (p99) |
| งานสแกนเสร็จ (ลูกค้าได้รับ LINE Push) | < 15 วินาที (p95) |
| ระบบพร้อมใช้งาน | 99.5% |
| อ่านใบเสร็จถูก (ร้านที่มี template) | > 95% |
| แต้มหาย | **0** (มี queue + DLQ + Excel รองรับ) |

> ตัวเลขพวกนี้คือเกณฑ์ว่าจะลงทุนเพิ่มตรงไหน — ถ้ายังไม่หลุด SLO **ไม่ต้องเพิ่มอะไร**

---

## ขั้นถัดไป

1. อ่านเอกสารนี้ → บอกว่าโอเคไหม / อยากปรับตรงไหน
2. **สร้าง scaffold** — วางไฟล์ทั้งหมดพร้อมโครง + คอมเมนต์อธิบายในแต่ละไฟล์
3. **เขียนทีละไฟล์ตาม Step 0 → 7** พร้อมอธิบายให้เข้าใจไปด้วยทุกไฟล์
