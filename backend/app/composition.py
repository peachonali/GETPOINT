"""★ จุดประกอบระบบ — สร้าง "ของจริง" จาก settings ที่เดียว

ทำไมมีไฟล์นี้ (ไม่มีในพิมพ์เขียว):
    main.py (web) กับ worker.py ต้องใช้ของชุดเดียวกันหลายตัว (Redis, CRM client, storage)
    ถ้าต่างคนต่างประกอบ วันหนึ่งจะตั้งค่าไม่ตรงกันเงียบๆ — เช่น web ใช้ timeout 10 วิ
    แต่ worker ใช้ 30 วิ แล้วอาการจะไปโผล่ตอน production หาสาเหตุยาก

    ไฟล์นี้จึงเป็น "สูตรประกอบเดียว" ที่ทั้งสอง process เรียกใช้

★ ที่นี่คือที่เดียวที่ตัดสินใจว่า "ใช้ของจริงหรือของปลอม" ตาม config
  ชั้นอื่นทั้งหมดรับ dependency ผ่าน constructor จึงไม่รู้และไม่สนใจ
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx
import redis as redis_lib
from redis import Redis

from app.config.settings import Settings
from app.external.crm_interface import CrmPort
from app.external.fake_notifier import FakeNotifier
from app.external.fake_sms import FakeSms
from app.external.line_client import LineClient
from app.external.loga_client import LogaClient
from app.external.loga_token import LogaTokenProvider
from app.external.notifier_interface import NotifierPort
from app.external.sms_client import SmsClient
from app.external.sms_interface import SmsPort
from app.jobs.job_queue import JobQueue
from app.jobs.job_status import JobStatusStore
from app.reliability.resilient_crm import ResilientCrm
from app.send_queue.send_queue import PointResender
from app.jobs.scan_job import ScanJobRunner
from app.member.member_link import MemberLinker
from app.member.member_service import MemberService
from app.member.otp_store import OtpStore
from app.observability.logging import get_logger
from app.ocr.fake_ocr import FakeOcr
from app.ocr.ocr_interface import OcrEngine
from app.ocr.paddle_ocr import PaddleOcr
from app.points.crm_formula_strategy import CrmFormulaStrategy
from app.points.point_service import PointService
from app.security.auth_guard import LineTokenVerifier
from app.security.rate_limit import RateLimiter
from app.storage.image_store import ImageStore
from app.storage.local_storage import LocalStorage
from app.storage.ocr_text_store import OcrTextStore

log = get_logger(__name__)

#: ขอ OTP ได้ไม่เกิน 5 ครั้ง / 10 นาที ต่อเบอร์ (กันเผา SMS ซึ่งมีค่าเงินต่อข้อความ)
OTP_REQUESTS_PER_WINDOW = 5
OTP_WINDOW_SECONDS = 600

_LOCAL_REDIS = "redis://localhost:6379/0"


@dataclass
class Shared:
    """ของที่ทั้ง web และ worker ใช้ร่วมกัน"""

    settings: Settings
    http: httpx.Client
    redis: Redis
    crm: CrmPort
    images: ImageStore
    ocr_text: OcrTextStore
    job_queue: JobQueue
    job_status: JobStatusStore

    def close(self) -> None:
        self.http.close()


def build_shared(settings: Settings) -> Shared:
    # httpx.Client ตัวเดียวแชร์ connection pool ให้ทุกปลายทาง (loga/LINE) — ประหยัดกว่าแยก
    http = httpx.Client()
    redis_client = redis_lib.from_url(settings.redis_url or _LOCAL_REDIS, decode_responses=True)

    token_provider = LogaTokenProvider(
        base_url=settings.loga_base_url,
        user=settings.loga_user,
        password=settings.loga_password,
        device_id=settings.loga_device_id,
        http_client=http,
        timeout_seconds=settings.loga_timeout_seconds,
    )
    # ★ ห่อ CRM ด้วย circuit breaker + retry ที่นี่ที่เดียว (composition root)
    #   ชั้นบนเห็นแค่ CrmPort ไม่รู้ว่ามีการห่อ — สลับเปิด/ปิดความทนล่มได้จากจุดนี้จุดเดียว
    crm = ResilientCrm(
        LogaClient(
            base_url=settings.loga_base_url,
            card_id=settings.loga_card_id,
            device_id=settings.loga_device_id,
            token_provider=token_provider,
            http_client=http,
            timeout_seconds=settings.loga_timeout_seconds,
        )
    )

    # รูปกับข้อความ OCR ใช้ storage ตัวเดียวกัน — ลบพร้อมกันตอน retention
    storage = LocalStorage(settings.storage_dir)

    return Shared(
        settings=settings,
        http=http,
        redis=redis_client,
        crm=crm,
        images=ImageStore(storage),
        ocr_text=OcrTextStore(storage),
        job_queue=JobQueue(redis_client),
        job_status=JobStatusStore(redis_client),
    )


# ═══════════════════════════════════════════
# ฝั่ง web
# ═══════════════════════════════════════════

def build_member_service(shared: Shared) -> MemberService:
    return MemberService(
        otp_store=OtpStore(shared.redis),
        sms=_build_sms(shared),
        linker=MemberLinker(shared.crm),
        otp_rate_limiter=RateLimiter(
            shared.redis, max_hits=OTP_REQUESTS_PER_WINDOW, window_seconds=OTP_WINDOW_SECONDS
        ),
    )


def build_line_verifier(shared: Shared) -> LineTokenVerifier:
    return LineTokenVerifier(
        channel_id=shared.settings.line_login_channel_id, http_client=shared.http
    )


# ═══════════════════════════════════════════
# ฝั่ง worker
# ═══════════════════════════════════════════

def build_scan_runner(shared: Shared) -> ScanJobRunner:
    return ScanJobRunner(
        image_store=shared.images,
        ocr=_build_ocr(shared),
        points=PointService(
            CrmFormulaStrategy(shared.crm, formula_id=shared.settings.loga_formula_id)
        ),
        notifier=_build_notifier(shared),
        status_store=shared.job_status,
        ocr_text_store=shared.ocr_text,
    )


def build_resender(shared: Shared) -> PointResender:
    """ตัวส่งแต้มค้าง (FAILED) เข้า CRM ใหม่ — worker เรียกเป็นรอบตอนว่างงาน"""
    return PointResender(shared.crm, formula_id=shared.settings.loga_formula_id)


# ═══════════════════════════════════════════
# เลือกของจริง/ของปลอมตาม config
# ═══════════════════════════════════════════

def _build_sms(shared: Shared) -> SmsPort:
    """มี api key = ส่งจริง · ไม่มี = FakeSms (dev — OTP โผล่ใน log แทนเข้ามือถือ)

    ⚠ prod ต้องตั้ง SMS_API_KEY + เขียน SmsClient ให้เสร็จ ไม่งั้น OTP ไม่ถึงลูกค้าจริง
    """
    if shared.settings.sms_api_key:
        return SmsClient(api_key=shared.settings.sms_api_key, base_url="", http_client=shared.http)

    log.warning("ยังไม่ได้ตั้ง SMS_API_KEY — ใช้ FakeSms (OTP จะไม่ถูกส่งเข้ามือถือจริง)")
    return FakeSms()


def _build_notifier(shared: Shared) -> NotifierPort:
    """มี LINE channel token = push จริง · ไม่มี = FakeNotifier"""
    if shared.settings.line_channel_token:
        return LineClient(
            channel_token=shared.settings.line_channel_token, http_client=shared.http
        )

    log.warning("ยังไม่ได้ตั้ง LINE_CHANNEL_TOKEN — ใช้ FakeNotifier (ลูกค้าจะไม่ได้รับ LINE)")
    return FakeNotifier()


def _build_ocr(shared: Shared) -> OcrEngine:
    """เลือก OCR ตาม config — prod ใช้ paddle, เทส/dev เร็วๆ ใช้ fake

    PaddleOcr โหลดโมเดลแบบ lazy (ครั้งแรกที่อ่านจริง) จึงสร้างตรงนี้ได้โดยไม่หน่วงตอนบูต
    """
    if shared.settings.ocr_engine == "fake":
        log.warning("ใช้ FakeOcr ตาม config (OCR_ENGINE=fake) — จะไม่อ่านรูปจริง")
        return FakeOcr()

    return PaddleOcr(lang=shared.settings.ocr_lang)
