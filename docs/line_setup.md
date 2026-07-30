# LINE Setup — คู่มือตั้งค่า LINE สำหรับ GETPOINT

> เอกสารนี้บอกว่าต้องสร้าง/ตั้งค่าอะไรฝั่ง LINE บ้าง และค่าไหนไปใส่ตรงไหนใน `.env`
> **หลักการ:** คุณเป็นคนใส่ค่าจริงลง `.env` เอง — โค้ดอ้างแค่ "ชื่อ" ไม่เคย hardcode ค่า

---

## ภาพรวม: GETPOINT ต้องใช้ 2 channel (ไม่ใช่ช่องเดียว)

| Channel | หน้าที่ในระบบเรา | สถานะ |
|---|---|---|
| **Messaging API** (= LINE OA) | Push แจ้งแต้ม "คุณได้รับ 25 แต้ม 🎉" | มี LINE OA แล้ว |
| **LINE Login** | ให้ลูกค้าเปิดหน้าสแกน (LIFF) ในแอป LINE + ระบุตัวตน | สมัคร LINE Login channel แล้ว |

ทั้งสอง channel อยู่ใน **LINE Developers Console** → https://developers.line.biz/console/
(login ด้วย LINE account เดียวกับที่สร้าง OA)

โครงสร้าง: `Provider` (เจ้าของ เช่น V-CLUB) → ข้างในมีได้หลาย channel

---

## 1. LINE Login channel (สำหรับ LIFF + ระบุตัวตน)

ใช้ยืนยันว่า request มาจาก LINE จริง และรู้ว่าเป็น `lineUserId` ไหน

**ค่าที่ต้องเก็บ** (อยู่ในแท็บ Basic settings ของ channel):

| ค่า | ระดับความลับ | ใช้ทำอะไร | ใส่ที่ |
|---|---|---|---|
| **Channel ID** | กึ่งสาธารณะ (identifier) | ตรวจว่า LIFF ID token เป็นของแอปเรา | `.env` → `LINE_LOGIN_CHANNEL_ID` |
| **Channel Secret** | 🔴 ลับสูง | (อาจใช้ verify token — จะยืนยันตอนเขียน auth) | รอก่อน อย่าเพิ่งใส่ |

> ⚠️ Channel Secret คือ secret ตัวจริง — ห้ามส่งให้ใคร ห้าม commit เก็บไว้ก่อน

### LIFF app (ทำทีหลัง — ตอน frontend เสร็จ)

LIFF ต้องกรอก **Endpoint URL** = URL ของหน้าเว็บ frontend ที่ deploy แล้ว
ตอนนี้ frontend ยังไม่เสร็จ → **ยังทำ LIFF ไม่ได้** รอไว้ก่อน
เมื่อทำแล้วจะได้ **LIFF ID** → ใส่ frontend config (ไม่ใช่ `.env` backend)

---

## 2. Messaging API channel (สำหรับ push แจ้งแต้ม — Step 3)

LINE OA ที่มีอยู่ผูกกับ Messaging API channel ได้ใน Developers Console

**ค่าที่ต้องเก็บ** (ทำตอน Step 3 ยังไม่ใช่ตอนนี้):

| ค่า | ระดับความลับ | ใช้ทำอะไร | ใส่ที่ |
|---|---|---|---|
| **Channel access token** | 🔴 ลับสูง | ส่ง push message แจ้งแต้ม | `.env` → `LINE_CHANNEL_TOKEN` (มีช่องแล้ว) |

---

## สรุป .env ฝั่ง LINE (ค่อยๆ เติมตาม Step)

```
# ใส่ตอนนี้ได้ (Step 2 — auth)
LINE_LOGIN_CHANNEL_ID=        # Channel ID ของ LINE Login channel

# ใส่ตอน Step 3 (push แจ้งแต้ม)
LINE_CHANNEL_TOKEN=           # Channel access token ของ Messaging API

# ใส่ frontend ตอนทำ LIFF (ไม่ใช่ backend .env)
# LIFF ID → frontend/src/config.ts
```

> UI ของ LINE Developers อาจต่างจากที่เขียนเล็กน้อยตามเวอร์ชัน — ถ้าหาไม่เจอ
> ดูคู่มือทางการที่ https://developers.line.biz/en/docs/
