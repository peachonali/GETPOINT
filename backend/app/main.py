"""web process — ★ composition root: ที่ที่ "ของจริง" ประกอบกันครั้งแรก

ตลอด Step 1-2 แต่ละชิ้นเทสด้วยของปลอม (fake_loga, fakeredis, mock LINE) เพื่อพิสูจน์
ตรรกะทีละส่วน · ไฟล์นี้คือที่ที่ประกอบ "ของจริง" จาก settings เข้าด้วยกันเป็นระบบ
แล้วเปิดเป็น HTTP endpoint

รันด้วย: uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
import redis as redis_lib
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config.settings import Settings, settings
from app.external.fake_sms import FakeSms
from app.external.loga_client import LogaClient
from app.external.loga_token import LogaTokenProvider
from app.external.sms_client import SmsClient
from app.member.member_link import MemberLinker
from app.member.member_service import MemberService
from app.member.otp_store import OtpStore
from app.observability.logging import get_logger, setup_logging
from app.reliability.errors import (
    AuthenticationError,
    ExternalServiceError,
    GetpointError,
    InputValidationError,
    RateLimitedError,
)
from app.routes import auth_routes, health_routes
from app.security.auth_guard import LineTokenVerifier
from app.security.rate_limit import RateLimiter

# ★ ต้องเรียกก่อนสร้างอะไร เพื่อให้ log ทุกบรรทัดตั้งแต่บูตผ่าน JSON + mask secret
# (ปิด Finding 3 จาก code review — เดิม logging เขียนเสร็จแต่ไม่มีใครเรียก)
setup_logging()
log = get_logger(__name__)

#: ขอ OTP ได้ไม่เกิน 5 ครั้ง / 10 นาที ต่อเบอร์ (กันเผา SMS)
OTP_REQUESTS_PER_WINDOW = 5
OTP_WINDOW_SECONDS = 600


def build_components(config: Settings) -> dict:
    """ประกอบของจริงจาก config — แยกฟังก์ชันเพื่อให้สคริปต์/เทสเรียกตรวจได้เอง

    httpx.Client ตัวเดียวแชร์ pool ให้ทั้ง loga และ LINE (ประหยัด connection)
    """
    http = httpx.Client()
    redis_client = redis_lib.from_url(
        config.redis_url or "redis://localhost:6379/0", decode_responses=True
    )

    token_provider = LogaTokenProvider(
        base_url=config.loga_base_url,
        user=config.loga_user,
        password=config.loga_password,
        device_id=config.loga_device_id,
        http_client=http,
        timeout_seconds=config.loga_timeout_seconds,
    )
    loga = LogaClient(
        base_url=config.loga_base_url,
        card_id=config.loga_card_id,
        device_id=config.loga_device_id,
        token_provider=token_provider,
        http_client=http,
        timeout_seconds=config.loga_timeout_seconds,
    )

    # มี SMS api key = ต่อ vendor จริง · ยังไม่มี = FakeSms (dev — OTP โผล่ใน log)
    # ⚠ prod ต้องตั้ง SMS_API_KEY + implement SmsClient ก่อน ไม่งั้น OTP ไม่ถึงลูกค้าจริง
    sms = (
        SmsClient(api_key=config.sms_api_key, base_url="", http_client=http)
        if config.sms_api_key
        else FakeSms()
    )

    member_service = MemberService(
        otp_store=OtpStore(redis_client),
        sms=sms,
        linker=MemberLinker(loga),
        otp_rate_limiter=RateLimiter(
            redis_client, max_hits=OTP_REQUESTS_PER_WINDOW, window_seconds=OTP_WINDOW_SECONDS
        ),
    )
    verifier = LineTokenVerifier(channel_id=config.line_login_channel_id, http_client=http)

    return {
        "http": http,
        "redis": redis_client,
        "member_service": member_service,
        "line_verifier": verifier,
        "default_tenant_id": config.default_tenant_id,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """สร้าง component ตอนบูต เก็บใน app.state · ปิด http client ตอนดับ"""
    components = build_components(settings)
    app.state.member_service = components["member_service"]
    app.state.line_verifier = components["line_verifier"]
    app.state.default_tenant_id = components["default_tenant_id"]
    app.state._http = components["http"]  # ถือ reference ไว้ปิดตอน shutdown
    app.state._redis = components["redis"]

    log.info("GETPOINT web เริ่มทำงาน")
    yield
    components["http"].close()


app = FastAPI(title="GETPOINT API", lifespan=lifespan)
app.include_router(health_routes.router)
app.include_router(auth_routes.router)


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
