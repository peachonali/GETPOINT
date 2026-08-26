"""web process — ★ ประตู HTTP ของระบบ

ประกอบ "ของจริง" จาก settings ผ่าน app/composition.py (สูตรเดียวกับที่ worker.py ใช้)
แล้วเปิดเป็น endpoint + แปลง error ของโดเมนเป็น HTTP status ที่เดียว

รันด้วย: uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.composition import build_line_verifier, build_member_service, build_shared
from app.config.settings import settings
from app.observability.logging import get_logger, setup_logging
from app.reliability.errors import (
    AuthenticationError,
    ExternalServiceError,
    GetpointError,
    InputValidationError,
    RateLimitedError,
)
from app.admin import queue_admin_routes
from app.routes import auth_routes, health_routes, job_routes, point_routes, scan_routes
from app.reliability.idempotency import IdempotencyStore
from app.security.rate_limit import RateLimiter

# ★ ต้องเรียกก่อนสร้างอะไร เพื่อให้ log ทุกบรรทัดตั้งแต่บูตผ่าน JSON + mask secret
setup_logging()
log = get_logger(__name__)

#: ส่งใบเสร็จได้ไม่เกิน 20 ใบ / 10 นาที ต่อคน — กันกดรัวถล่ม worker
SCAN_UPLOADS_PER_WINDOW = 20
SCAN_WINDOW_SECONDS = 600


@asynccontextmanager
async def lifespan(app: FastAPI):
    """ประกอบของจริงตอนบูต เก็บใน app.state · ปิด connection ตอนดับ"""
    shared = build_shared(settings)

    app.state.member_service = build_member_service(shared)
    app.state.line_verifier = build_line_verifier(shared)
    app.state.default_tenant_id = shared.settings.default_tenant_id
    app.state.image_store = shared.images
    app.state.job_queue = shared.job_queue
    app.state.job_status = shared.job_status
    app.state.admin_token = shared.settings.admin_token
    app.state.formula_id = shared.settings.loga_formula_id
    app.state.crm = shared.crm
    app.state.scan_rate_limiter = RateLimiter(
        shared.redis, max_hits=SCAN_UPLOADS_PER_WINDOW, window_seconds=SCAN_WINDOW_SECONDS
    )
    app.state.idempotency = IdempotencyStore(shared.redis)

    log.info("GETPOINT web เริ่มทำงาน")
    yield
    shared.close()


app = FastAPI(title="GETPOINT API", lifespan=lifespan)
app.include_router(health_routes.router)
app.include_router(auth_routes.router)
app.include_router(scan_routes.router)
app.include_router(job_routes.router)
app.include_router(point_routes.router)
app.include_router(queue_admin_routes.router)


# ═══════════════════════════════════════════
# แปลง error ของโดเมน → HTTP status (ที่เดียวของทั้งระบบ)
# ชั้น route/service จึงแค่ "โยน error ที่มีความหมาย" ไม่ต้องรู้เรื่อง HTTP
# ═══════════════════════════════════════════

def _json(status: int, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message, **extra})


@app.exception_handler(InputValidationError)
async def _handle_input(request: Request, exc: InputValidationError) -> JSONResponse:
    return _json(400, str(exc))


@app.exception_handler(AuthenticationError)
async def _handle_auth(request: Request, exc: AuthenticationError) -> JSONResponse:
    return _json(401, "ยืนยันตัวตนไม่ผ่าน กรุณาเข้าผ่าน LINE อีกครั้ง")


@app.exception_handler(RateLimitedError)
async def _handle_rate(request: Request, exc: RateLimitedError) -> JSONResponse:
    # ส่ง Retry-After ตามมาตรฐาน HTTP ให้ client/แอปรู้ว่ารออีกกี่วินาที
    response = _json(429, str(exc), retry_after_seconds=exc.retry_after_seconds)
    response.headers["Retry-After"] = str(exc.retry_after_seconds)
    return response


@app.exception_handler(ExternalServiceError)
async def _handle_external(request: Request, exc: ExternalServiceError) -> JSONResponse:
    # รวม CrmAuthError/CrmCallError (loga) + LINE ล่ม — ปัญหาฝั่งระบบ ไม่โทษ input ลูกค้า
    # ไม่ส่งรายละเอียดภายในออกไป (กัน leak ว่าเป็น loga/line) — log ไว้ debug ต่างหาก
    log.warning("external service error", extra={"service": exc.service, "detail": str(exc)})
    return _json(502, "บริการภายนอกขัดข้องชั่วคราว กรุณาลองใหม่อีกครั้ง")


@app.exception_handler(GetpointError)
async def _handle_generic(request: Request, exc: GetpointError) -> JSONResponse:
    # ตาข่ายสุดท้ายสำหรับ error ของเราที่ยังไม่มี handler เฉพาะ
    log.error("unhandled domain error", extra={"detail": str(exc)})
    return _json(500, "เกิดข้อผิดพลาดภายในระบบ")
