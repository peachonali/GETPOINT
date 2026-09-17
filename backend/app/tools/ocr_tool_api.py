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

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response

from app.observability.logging import get_logger, setup_logging
from app.security.upload_check import check_and_clean_image
from app.tools.ocr_excel import build_excel
from app.tools.ocr_extract import extract_one, warm_up

setup_logging()
log = get_logger(__name__)

#: กันอัปโหลดทีเดียวเยอะเกินจนเครื่องแฮงค์ (OCR กิน CPU ~8 วิ/ใบ)
_MAX_FILES_PER_BATCH = 30


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """อุ่นโมเดล OCR ตอนบูต — ★ สำคัญตอน deploy จริง

    ถ้าไม่อุ่นไว้ ลูกค้าคนแรกที่สแกนจะรอ ~20 วิ (โหลดโมเดล) แล้วนึกว่าเว็บค้าง
    อุ่นตอนบูตทำให้ทุกคำขอเร็วตั้งแต่ใบแรก · ปิดได้ด้วย OCR_WARMUP=0 (เช่นตอนเทส)
    """
    if os.getenv("OCR_WARMUP", "1") != "0":
        log.info("กำลังอุ่นโมเดล OCR...")
        warm_up()
        log.info("อุ่นโมเดล OCR เสร็จ พร้อมรับงาน")
    yield


app = FastAPI(title="GETPOINT OCR Tool", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    """ให้ platform/tunnel เช็คว่าเว็บยังมีชีวิต (ไม่โหลดโมเดล ตอบเร็ว)"""
    return {"status": "ok"}


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


# ── หน้าเว็บแบบแอป (mobile-first, อยู่ในไฟล์เดียว ไม่ต้อง build) ──
#
# ★ แก้บั๊กมือถือที่ "ถ่ายรูปแล้วกดอ่านไม่ได้":
#   - แยก input "ถ่ายรูป" (capture) กับ "เลือกจากคลัง" (multiple) ออกจากกัน
#     เพราะ capture+multiple พร้อมกันมีปัญหาบนหลายมือถือ (ไฟล์ไม่เข้า)
#   - ใช้ปุ่มเรียก input.click() ครั้งเดียว ไม่ซ้อน input ใน label (กันเปิดกล้อง 2 รอบ
#     ซึ่งทำให้ไฟล์ที่เพิ่งถ่ายหลุดหาย)
#   - เคลียร์ input.value หลังหยิบไฟล์ → ถ่าย/เลือกไฟล์เดิมซ้ำได้ และสะสมได้ทีละใบ
_PAGE = """<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#5b3df5">
<title>V-CLUB · สแกนใบเสร็จ</title>
<style>
  :root{
    --brand:#5b3df5; --brand-2:#7c5cff; --bg:#0f1220; --card:#171a2b; --card-2:#1f2338;
    --ink:#f3f4f8; --muted:#9aa0b4; --line:#2a2f47; --ok:#34d399; --bad:#fb7185;
    --shadow:0 10px 30px rgba(0,0,0,.35);
  }
  *{box-sizing:border-box; -webkit-tap-highlight-color:transparent;}
  html,body{margin:0; background:var(--bg); color:var(--ink);
    font-family:system-ui,-apple-system,"Segoe UI","Noto Sans Thai",sans-serif;}
  body{min-height:100dvh; padding-bottom:96px;}
  .top{position:sticky; top:0; z-index:20; padding:14px 16px calc(14px + env(safe-area-inset-top));
    padding-top:calc(14px + env(safe-area-inset-top));
    background:linear-gradient(135deg,var(--brand),var(--brand-2)); box-shadow:var(--shadow);}
  .top h1{margin:0; font-size:17px; font-weight:800; letter-spacing:.2px;}
  .top p{margin:3px 0 0; font-size:12px; color:#e7e4ff; opacity:.9;}
  main{max-width:640px; margin:0 auto; padding:16px;}

  /* empty state */
  .hero{text-align:center; padding:30px 16px;}
  .hero .icon{font-size:56px; margin-bottom:6px;}
  .hero h2{margin:6px 0 4px; font-size:18px;}
  .hero p{margin:0 0 20px; color:var(--muted); font-size:13px;}

  .add-row{display:flex; gap:12px;}
  .add-btn{flex:1; border:0; border-radius:16px; padding:18px 10px; cursor:pointer;
    background:var(--card); color:var(--ink); box-shadow:var(--shadow);
    display:flex; flex-direction:column; align-items:center; gap:8px; font-size:14px; font-weight:700;
    border:1px solid var(--line);}
  .add-btn .em{font-size:26px;}
  .add-btn:active{transform:scale(.97);}
  .add-btn.cam{background:linear-gradient(135deg,var(--brand),var(--brand-2)); border:0;}

  /* queue cards */
  .cards{display:flex; flex-direction:column; gap:12px; margin-top:16px;}
  .rc{background:var(--card); border:1px solid var(--line); border-radius:16px; overflow:hidden;
    box-shadow:var(--shadow);}
  .rc-head{display:flex; gap:12px; padding:12px; align-items:center;}
  .thumb{width:56px; height:56px; border-radius:12px; object-fit:cover; background:var(--card-2); flex:none;}
  .rc-main{flex:1; min-width:0;}
  .rc-title{font-size:13px; color:var(--muted); white-space:nowrap; overflow:hidden;
    text-overflow:ellipsis;}
  .amount{font-size:26px; font-weight:800; line-height:1.1; margin-top:2px;}
  .amount small{font-size:13px; color:var(--muted); font-weight:600;}
  .pending{font-size:13px; color:var(--muted);}
  .rc-x{border:0; background:transparent; color:var(--muted); font-size:22px; padding:4px 8px;
    cursor:pointer; flex:none;}
  .chips{display:flex; flex-wrap:wrap; gap:6px; padding:0 12px 12px;}
  .chip{font-size:12px; background:var(--card-2); color:var(--ink); border:1px solid var(--line);
    padding:4px 9px; border-radius:999px;}
  .chip.ok{color:var(--ok); border-color:rgba(52,211,153,.4);}
  .chip.bad{color:var(--bad); border-color:rgba(251,113,133,.4);}
  .items{font-size:12.5px; color:var(--muted); padding:0 12px 12px; line-height:1.5;}
  details.raw{padding:0 12px 12px;}
  details.raw summary{font-size:12px; color:var(--muted); cursor:pointer;}
  details.raw pre{margin:8px 0 0; font-size:11px; color:var(--muted); white-space:pre-wrap;
    background:var(--bg); padding:10px; border-radius:10px; max-height:180px; overflow:auto;}

  /* sticky bottom bar */
  .bar{position:fixed; left:0; right:0; bottom:0; z-index:30;
    padding:12px 16px calc(12px + env(safe-area-inset-bottom));
    background:rgba(15,18,32,.9); backdrop-filter:blur(10px); border-top:1px solid var(--line);
    display:flex; gap:10px; max-width:640px; margin:0 auto;}
  .btn{flex:1; border:0; border-radius:14px; padding:15px; font-size:15px; font-weight:800;
    cursor:pointer;}
  .btn:active{transform:scale(.98);}
  .btn.primary{background:linear-gradient(135deg,var(--brand),var(--brand-2)); color:#fff;}
  .btn.ghost{background:var(--card); color:var(--ink); border:1px solid var(--line);}
  .btn:disabled{opacity:.45;}

  .toast{position:fixed; left:50%; bottom:110px; transform:translateX(-50%); z-index:40;
    background:var(--card-2); color:var(--ink); border:1px solid var(--line); padding:10px 16px;
    border-radius:999px; font-size:13px; box-shadow:var(--shadow); opacity:0; transition:opacity .2s;
    pointer-events:none; max-width:90vw; text-align:center;}
  .toast.show{opacity:1;}

  /* processing overlay */
  .overlay{position:fixed; inset:0; z-index:50; background:rgba(15,18,32,.72);
    backdrop-filter:blur(4px); display:none; align-items:center; justify-content:center;
    flex-direction:column; gap:16px;}
  .overlay.show{display:flex;}
  .spin{width:52px; height:52px; border-radius:50%; border:5px solid var(--line);
    border-top-color:var(--brand-2); animation:spin 1s linear infinite;}
  @keyframes spin{to{transform:rotate(360deg);}}
  .overlay p{color:var(--ink); font-size:14px; margin:0;}
</style>
</head>
<body>
  <div class="top">
    <h1>V-CLUB · สแกนใบเสร็จ</h1>
    <p>ถ่ายใบเสร็จ → ระบบอ่านให้ → บันทึกเป็น Excel</p>
  </div>

  <main>
    <div id="empty" class="hero">
      <div class="icon">🧾</div>
      <h2>เริ่มสแกนใบเสร็จ</h2>
      <p>ถ่ายทีละใบก็ได้ สะสมได้หลายใบก่อนกดอ่าน</p>
      <div class="add-row">
        <button class="add-btn cam" id="btnCam"><span class="em">📷</span>ถ่ายรูป</button>
        <button class="add-btn" id="btnGallery"><span class="em">🖼️</span>เลือกจากคลัง</button>
      </div>
    </div>

    <div id="queue" style="display:none">
      <div class="add-row">
        <button class="add-btn cam" id="btnCam2"><span class="em">📷</span>ถ่ายเพิ่ม</button>
        <button class="add-btn" id="btnGallery2"><span class="em">🖼️</span>เลือกเพิ่ม</button>
      </div>
      <div class="cards" id="cards"></div>
    </div>
  </main>

  <div class="bar" id="bar" style="display:none">
    <button class="btn primary" id="btnRead">อ่านใบเสร็จ</button>
    <button class="btn ghost" id="btnExcel" disabled>⬇ Excel</button>
  </div>

  <div class="overlay" id="overlay">
    <div class="spin"></div>
    <p id="overlayMsg">กำลังอ่าน...</p>
  </div>
  <div class="toast" id="toast"></div>

  <!-- input แยกกัน: กล้อง (ถ่ายทีละใบ) กับ คลัง (หลายใบ) -->
  <input id="camInput" type="file" accept="image/*" capture="environment" hidden>
  <input id="galleryInput" type="file" accept="image/*" multiple hidden>

<script>
  const $ = (id) => document.getElementById(id);
  let seq = 0;
  const items = [];          // {id, file, url, result}
  let hasRead = false;

  // ── เลือกไฟล์: ปุ่มเรียก input.click() ครั้งเดียว (ไม่ซ้อน label = ไม่เปิดกล้องซ้ำ) ──
  $("btnCam").onclick = $("btnCam2").onclick = () => $("camInput").click();
  $("btnGallery").onclick = $("btnGallery2").onclick = () => $("galleryInput").click();

  $("camInput").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
  $("galleryInput").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });

  function addFiles(fileList) {
    for (const file of Array.from(fileList)) {
      if (!file.type.startsWith("image/")) continue;
      items.push({ id: ++seq, file, url: URL.createObjectURL(file), result: null });
    }
    hasRead = false;
    $("btnExcel").disabled = true;
    render();
  }

  function removeItem(id) {
    const i = items.findIndex((x) => x.id === id);
    if (i >= 0) { URL.revokeObjectURL(items[i].url); items.splice(i, 1); render(); }
  }

  function render() {
    const has = items.length > 0;
    $("empty").style.display = has ? "none" : "block";
    $("queue").style.display = has ? "block" : "none";
    $("bar").style.display = has ? "flex" : "none";
    $("btnRead").disabled = !has;
    $("btnRead").textContent = has ? `อ่านใบเสร็จ (${items.length})` : "อ่านใบเสร็จ";

    const box = $("cards");
    box.innerHTML = "";
    for (const it of items) box.appendChild(card(it));
  }

  function card(it) {
    const el = document.createElement("div");
    el.className = "rc";
    const r = it.result;
    let body;
    if (!r) {
      body = `<div class="rc-main"><div class="rc-title">${esc(it.file.name)}</div>
              <div class="pending">รอกดอ่าน</div></div>
              <button class="rc-x" aria-label="ลบ">✕</button>`;
    } else if (r.ok) {
      body = `<div class="rc-main"><div class="rc-title">${esc(r.merchant || "-")}</div>
              <div class="amount">${Number(r.total_amount).toLocaleString()} <small>บาท</small></div></div>
              <button class="rc-x" aria-label="ลบ">✕</button>`;
    } else {
      body = `<div class="rc-main"><div class="rc-title">${esc(it.file.name)}</div>
              <div class="amount" style="font-size:16px;color:var(--bad)">อ่านไม่ได้</div></div>
              <button class="rc-x" aria-label="ลบ">✕</button>`;
    }
    el.innerHTML = `<div class="rc-head"><img class="thumb" src="${it.url}" alt="">${body}</div>`;
    el.querySelector(".rc-x").onclick = () => removeItem(it.id);

    if (r) {
      const chips = [];
      chips.push(`<span class="chip ${r.ok ? "ok" : "bad"}">${r.ok ? "✓ อ่านได้" : "✗ อ่านไม่ได้"}</span>`);
      if (r.merchant_code) chips.push(`<span class="chip">${esc(r.merchant_code)}</span>`);
      if (r.receipt_date) chips.push(`<span class="chip">${esc(r.receipt_date)}</span>`);
      if (r.receipt_time) chips.push(`<span class="chip">${esc(r.receipt_time)}</span>`);
      if (r.reference_codes) chips.push(`<span class="chip">${esc(r.reference_codes)}</span>`);
      el.innerHTML += `<div class="chips">${chips.join("")}</div>`;
      if (r.items) el.innerHTML += `<div class="items">🛒 ${esc(r.items)}</div>`;
      el.innerHTML += `<details class="raw"><summary>ดูข้อความ OCR ดิบ</summary>
                       <pre>${esc(r.raw_text || r.reason || "")}</pre></details>`;
      // ปุ่มลบถูกเขียนทับตอน innerHTML += → ผูก event ใหม่
      el.querySelector(".rc-x").onclick = () => removeItem(it.id);
    }
    return el;
  }

  function formData() {
    const fd = new FormData();
    items.forEach((it) => fd.append("files", it.file, it.file.name));
    return fd;
  }

  $("btnRead").onclick = async () => {
    if (!items.length) return;
    showOverlay("กำลังอ่าน " + items.length + " ใบ...\\n(ครั้งแรกอาจนานหน่อย)");
    try {
      const resp = await fetch("/api/extract", { method: "POST", body: formData() });
      if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || "อ่านไม่สำเร็จ");
      const rows = (await resp.json()).rows || [];
      rows.forEach((row, i) => { if (items[i]) items[i].result = row; });
      hasRead = true;
      $("btnExcel").disabled = false;
      render();
      const ok = rows.filter((x) => x.ok).length;
      toast(`อ่านได้ ${ok}/${rows.length} ใบ`);
    } catch (e) { toast("❌ " + e.message); }
    finally { hideOverlay(); }
  };

  $("btnExcel").onclick = async () => {
    showOverlay("กำลังสร้าง Excel...");
    try {
      const resp = await fetch("/api/export.xlsx", { method: "POST", body: formData() });
      if (!resp.ok) throw new Error("สร้างไฟล์ไม่สำเร็จ");
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "receipts_" + new Date().toISOString().slice(0, 10) + ".xlsx";
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
      toast("✅ ดาวน์โหลด Excel แล้ว");
    } catch (e) { toast("❌ " + e.message); }
    finally { hideOverlay(); }
  };

  let toastTimer;
  function toast(msg) {
    const t = $("toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
  }
  function showOverlay(msg) { $("overlayMsg").textContent = msg; $("overlay").classList.add("show"); }
  function hideOverlay() { $("overlay").classList.remove("show"); }
  function esc(s) {
    return String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  }
</script>
</body>
</html>"""
