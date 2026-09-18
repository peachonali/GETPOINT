# เปิดเครื่องมืออ่านใบเสร็จ + เปิด public link (Cloudflare Tunnel) ในคำสั่งเดียว
#
# ใช้ยังไง (ดับเบิลคลิกไม่ได้ ต้องเปิด PowerShell แล้วรัน):
#     cd C:\Users\ASUS\Desktop\getpoint
#     .\start-ocr-tool.ps1
#
# ต้องมี cloudflared.exe ก่อน (ดู docs/DEPLOY.md ขั้น A2) — วางไว้ที่ใดที่หนึ่งใน 3 ที่:
#   1) โฟลเดอร์นี้ (getpoint\cloudflared.exe)
#   2) C:\Users\ASUS\cloudflared.exe
#   3) อยู่ใน PATH อยู่แล้ว

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"

# หา cloudflared.exe
$cf = @(
    (Join-Path $root "cloudflared.exe"),
    "C:\Users\ASUS\cloudflared.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $cf) {
    if (Get-Command cloudflared -ErrorAction SilentlyContinue) { $cf = "cloudflared" }
}
if (-not $cf) {
    Write-Host "❌ ไม่พบ cloudflared.exe — ดูวิธีโหลดที่ docs/DEPLOY.md ขั้น A2" -ForegroundColor Red
    exit 1
}

Write-Host "▶ เปิดเซิร์ฟเวอร์ OCR (หน้าต่างใหม่)..." -ForegroundColor Cyan
# เปิด uvicorn ในหน้าต่างใหม่ เพื่อให้ tunnel รันในหน้าต่างนี้เห็นลิงก์ชัด
#
# ★ ห่อด้วย while ($true) ให้ "รีสตาร์ทเองถ้าดับ" — PaddleOCR เคย segfault (exit 139)
#   กับรูปมือถือความละเอียดสูงบางใบ (ย่อขนาดช่วยลดโอกาสมากแล้ว แต่กันเหนียวไว้)
#   ถ้าเซิร์ฟเวอร์ดับกลางทาง ลิงก์จะกลับมาใช้ได้เองใน ~25 วิ ไม่ต้องมานั่งเปิดใหม่
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "cd '$backend'; while (`$true) { python -m uvicorn app.tools.ocr_tool_api:app --host 0.0.0.0 --port 8100; Write-Host 'เซิร์ฟเวอร์ดับ — กำลังรีสตาร์ทใน 3 วิ...' -ForegroundColor Yellow; Start-Sleep 3 }"
)

Write-Host "⏳ รออุ่นโมเดล OCR ~25 วินาที..." -ForegroundColor Cyan
Start-Sleep -Seconds 25

Write-Host "▶ เปิด public link (Cloudflare Tunnel)..." -ForegroundColor Cyan
Write-Host "  มองหาบรรทัด https://xxxx.trycloudflare.com ด้านล่าง แล้วเอาไปใส่ LINE rich menu" -ForegroundColor Yellow
Write-Host ""
& $cf tunnel --url http://localhost:8100
