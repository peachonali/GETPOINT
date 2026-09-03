"""★ เครื่องมือฝึก OCR — เว็บง่ายๆ: อัปโหลด/ถ่ายใบเสร็จ → OCR จริงอ่าน → โหลด Excel

ทำไมแยกจากระบบหลัก (app/main.py):
  ระบบหลักเป็นสายลูกค้า (LINE login → OTP → คิว → worker → loga → LINE push)
  ซึ่งตอนนี้ยังติด LINE/loga · เครื่องมือนี้ตัดทุกอย่างนั้นทิ้ง เหลือแค่
      รูป → OCR จริง → ผล/Excel
  ไม่มี LINE ไม่มี loga ไม่มี DB ไม่มีการจำลอง — เอาไว้ป้อนรูปฝึกเรื่อยๆ ได้ทันที

รันด้วย (จาก backend/):
    uvicorn app.tools.ocr_tool_api:app --host 0.0.0.0 --port 8100
แล้วเปิด http://localhost:8100

★ OCR ทำงานแบบ synchronous ในคำขอเดียว (รอผลเลย) — ต่างจากระบบหลักที่ async
  เพราะเครื่องมือฝึกใช้คนเดียว รอ ~8 วิ/ใบ รับได้ และง่ายกว่ามาก (ไม่ต้องมีคิว/worker)
  แต่ยังโหลดโมเดลครั้งเดียวใช้ซ้ำ (ดู ocr_extract._get_ocr) จึงเร็วตั้งแต่ใบที่สอง
"""
from __future__ import annotations

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response

from app.observability.logging import get_logger, setup_logging
from app.security.upload_check import check_and_clean_image
from app.tools.ocr_excel import build_excel
from app.tools.ocr_extract import extract_one

setup_logging()
log = get_logger(__name__)

app = FastAPI(title="GETPOINT OCR Tool")

#: กันอัปโหลดทีเดียวเยอะเกินจนเครื่องแฮงค์ (OCR กิน CPU ~8 วิ/ใบ)
_MAX_FILES_PER_BATCH = 30


@app.post("/api/extract")
async def extract(files: list[UploadFile] = File(...)) -> dict:
    """อ่านใบเสร็จที่อัปโหลดมา (หลายใบได้) → คืนผลเป็น JSON ให้หน้าเว็บแสดงตาราง"""
    rows = _read_all(await _collect(files))
    return {"count": len(rows), "rows": rows}


@app.post("/api/export.xlsx")
async def export(files: list[UploadFile] = File(...)) -> Response:
    """อ่านใบเสร็จที่อัปโหลดมา → ดาวน์โหลดผลเป็น Excel ทันที"""
    rows = _read_all(await _collect(files))
    content = build_excel(rows)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="receipts_ocr.xlsx"'},
    )


async def _collect(files: list[UploadFile]) -> list[tuple[str, bytes]]:
    """อ่านไฟล์ที่อัปโหลด + ตรวจว่าเป็นรูปจริง (magic bytes) + ล้าง EXIF

    ใช้ upload_check ตัวเดียวกับระบบหลัก — รับของจากภายนอกต้องตรวจเหมือนกัน (DEV ข้อ 3.2)
    """
    if not files:
        raise HTTPException(status_code=400, detail="ยังไม่ได้เลือกไฟล์")
    if len(files) > _MAX_FILES_PER_BATCH:
        raise HTTPException(status_code=400, detail=f"อัปโหลดได้ครั้งละไม่เกิน {_MAX_FILES_PER_BATCH} ใบ")

    collected: list[tuple[str, bytes]] = []
    for upload in files:
        raw = await upload.read()
        try:
            cleaned = check_and_clean_image(raw)
        except Exception as exc:  # noqa: BLE001 — ไฟล์ไม่ใช่รูป/เสีย → ข้ามใบนั้น ไม่ล้มทั้งชุด
            log.info("ไฟล์ไม่ผ่านการตรวจ ข้ามไป", extra={"file": upload.filename})
            collected.append((upload.filename or "unknown", b""))
            continue
        collected.append((upload.filename or "unknown", cleaned))
    return collected


def _read_all(items: list[tuple[str, bytes]]) -> list[dict]:
    rows = []
    for name, image in items:
        if not image:
            rows.append({"filename": name, "ok": False, "reason": "ไฟล์ไม่ใช่รูปหรือเสียหาย",
                         "merchant": "", "merchant_code": "", "total_amount": None,
                         "receipt_date": "", "receipt_time": "", "reference_codes": "",
                         "items": "", "raw_text": ""})
            continue
        rows.append(extract_one(name, image))
    return rows


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return _PAGE


# ── หน้าเว็บ (อยู่ในไฟล์เดียว ไม่ต้องมี build step) ──
# capture="environment" บนมือถือ = เปิดกล้องถ่ายได้เลย (ตรงกับ "สแกน" ไม่ใช่แค่แนบรูป)
_PAGE = """<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GETPOINT · เครื่องมืออ่านใบเสร็จ</title>
<style>
  :root { --bg:#f6f7fb; --card:#fff; --ink:#1f2430; --muted:#6b7280; --brand:#5b3df5; --ok:#16a34a; --bad:#dc2626; --line:#e5e7eb; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font-family:system-ui,"Segoe UI",sans-serif; }
  header { background:var(--brand); color:#fff; padding:18px 20px; }
  header h1 { margin:0; font-size:18px; }
  header p { margin:4px 0 0; opacity:.85; font-size:13px; }
  main { max-width:1100px; margin:0 auto; padding:20px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:18px; margin-bottom:16px; }
  .drop { border:2px dashed #cbd5e1; border-radius:14px; padding:28px; text-align:center; color:var(--muted); cursor:pointer; }
  .drop:hover { border-color:var(--brand); color:var(--brand); }
  .row { display:flex; gap:10px; flex-wrap:wrap; margin-top:14px; }
  button { border:0; border-radius:10px; padding:11px 18px; font-size:15px; font-weight:600; cursor:pointer; }
  .primary { background:var(--brand); color:#fff; }
  .ghost { background:#eef0f6; color:var(--ink); }
  button:disabled { opacity:.5; cursor:default; }
  #status { margin-top:12px; font-size:14px; color:var(--muted); }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th,td { border-bottom:1px solid var(--line); padding:8px 10px; text-align:left; vertical-align:top; }
  th { background:#fafafe; position:sticky; top:0; }
  td.amount { font-weight:700; white-space:nowrap; }
  .badge-ok { color:var(--ok); font-weight:700; }
  .badge-bad { color:var(--bad); font-weight:700; }
  .raw { font-family:ui-monospace,monospace; font-size:11px; color:var(--muted); white-space:pre-wrap; max-width:320px; max-height:120px; overflow:auto; }
  .count { font-size:13px; color:var(--muted); }
</style>
</head>
<body>
<header>
  <h1>GETPOINT · เครื่องมืออ่านใบเสร็จ</h1>
  <p>อัปโหลดหรือถ่ายใบเสร็จ → ระบบอ่านจริง → โหลดผลเป็น Excel · (ยังไม่เชื่อม loga)</p>
</header>
<main>
  <div class="card">
    <label class="drop" id="drop">
      📸 แตะเพื่อถ่าย หรือเลือกรูปใบเสร็จ (เลือกหลายใบพร้อมกันได้)
      <input id="file" type="file" accept="image/*" capture="environment" multiple hidden>
    </label>
    <div class="row">
      <button class="primary" id="btnRead" disabled>อ่านใบเสร็จ</button>
      <button class="ghost" id="btnExcel" disabled>⬇ ดาวน์โหลด Excel</button>
      <span class="count" id="picked"></span>
    </div>
    <div id="status"></div>
  </div>

  <div class="card" id="resultCard" style="display:none">
    <div class="count" id="summary"></div>
    <div style="overflow:auto; max-height:70vh">
      <table id="tbl">
        <thead><tr>
          <th>ไฟล์</th><th>อ่านได้</th><th>ยอดเงิน</th><th>ร้าน</th><th>วันที่</th><th>เวลา</th>
          <th>เลขอ้างอิง</th><th>รายการสินค้า</th><th>ข้อความ OCR ดิบ</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>
</main>
<script>
  const $ = (id) => document.getElementById(id);
  const fileInput = $("file");
  let picked = [];

  $("drop").addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    picked = Array.from(fileInput.files);
    $("picked").textContent = picked.length ? `เลือกแล้ว ${picked.length} ใบ` : "";
    $("btnRead").disabled = picked.length === 0;
    $("btnExcel").disabled = picked.length === 0;
  });

  function formData() {
    const fd = new FormData();
    picked.forEach((f) => fd.append("files", f));
    return fd;
  }

  $("btnRead").addEventListener("click", async () => {
    setBusy("กำลังอ่าน... (ใบแรกโหลดโมเดล ~20 วิ ใบต่อไปเร็ว)");
    try {
      const resp = await fetch("/api/extract", { method: "POST", body: formData() });
      if (!resp.ok) throw new Error((await resp.json()).detail || "อ่านไม่สำเร็จ");
      render((await resp.json()).rows);
      setBusy("");
    } catch (e) { setBusy("❌ " + e.message); }
  });

  $("btnExcel").addEventListener("click", async () => {
    setBusy("กำลังสร้าง Excel...");
    try {
      const resp = await fetch("/api/export.xlsx", { method: "POST", body: formData() });
      if (!resp.ok) throw new Error((await resp.json()).detail || "สร้างไฟล์ไม่สำเร็จ");
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = "receipts_ocr.xlsx"; a.click();
      URL.revokeObjectURL(url);
      setBusy("✅ ดาวน์โหลดแล้ว");
    } catch (e) { setBusy("❌ " + e.message); }
  });

  function setBusy(msg) {
    $("status").textContent = msg;
    const busy = msg.startsWith("กำลัง");
    $("btnRead").disabled = busy || picked.length === 0;
    $("btnExcel").disabled = busy || picked.length === 0;
  }

  function render(rows) {
    $("resultCard").style.display = "block";
    const ok = rows.filter((r) => r.ok).length;
    $("summary").textContent = `อ่านได้ ${ok}/${rows.length} ใบ`;
    const tb = $("tbl").querySelector("tbody");
    tb.innerHTML = "";
    for (const r of rows) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${esc(r.filename)}</td>
        <td class="${r.ok ? "badge-ok" : "badge-bad"}">${r.ok ? "✓" : "✗"}</td>
        <td class="amount">${r.total_amount == null ? "-" : Number(r.total_amount).toLocaleString()}</td>
        <td>${esc(r.merchant)}${r.merchant_code ? ` <small>(${esc(r.merchant_code)})</small>` : ""}</td>
        <td>${esc(r.receipt_date)}</td>
        <td>${esc(r.receipt_time)}</td>
        <td>${esc(r.reference_codes)}</td>
        <td>${esc(r.items)}</td>
        <td><div class="raw">${esc(r.raw_text || r.reason)}</div></td>`;
      tb.appendChild(tr);
    }
  }

  function esc(s) {
    return String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  }
</script>
</body>
</html>"""
