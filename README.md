# GETPOINT

Middleware สแกนใบเสร็จ → แปลงยอดเงินเป็นแต้ม บน LINE OA (V-CLUB) → ส่งเข้า CRM (loga).

## โครงสร้าง
- `frontend/` — LIFF (TypeScript + React)
- `backend/` — FastAPI: `main.py` (web) + `worker.py` (งานหนัก) แยก process
- `tests/`, `docs/` — เทส + เอกสาร (ADR, SLO)

## รัน (dev)
`docker-compose up`  → เปิด http://localhost:8000/health

## รันเทส
```
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
pytest
```
(`pytest.ini` ชี้ `pythonpath = backend` ไว้แล้ว — สั่ง `pytest` จาก root ได้เลย)

## ลำดับการเขียน
ดู `GETPOINT_blueprint_v3.md` ส่วนที่ 5 (Step 0 → 6).

## ยังไม่สร้างในเฟสนี้ (สร้างเมื่อถึงเวลา)
Method A point engine, template_monitor, retention_worker, metrics, audit_log,
amount/date check, threat_model, runbook, Kafka/K8s/multi-region/GPU.
