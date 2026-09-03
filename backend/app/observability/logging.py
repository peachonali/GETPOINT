"""ตั้งค่า log ของทั้งระบบ + ปิดบัง secret ก่อน log + ผูก job_id/receipt_id ทุกบรรทัด

ทำไมไฟล์นี้ต้องมาก่อน external/*:
    loga ส่ง token กับ password มาใน "query string" (แก้ที่ฝั่งเขาไม่ได้)
    ถ้าเขียน client ก่อนมีตัว mask เราจะได้ client ที่ log credential หลุดตั้งแต่ไฟล์แรก

กันข้อมูลหลุด 2 ชั้น:
    ชั้นที่ 1 (ตั้งใจ) — คนเรียกใช้ safe_url() ตัด query string ทิ้งก่อน log เอง
    ชั้นที่ 2 (ตาข่าย)  — formatter mask ทุกบรรทัดก่อนออกจอ เผื่อชั้นที่ 1 พลาด

วิธีใช้:
    from app.observability.logging import setup_logging, get_logger, log_context

    setup_logging()                       # เรียกครั้งเดียวตอนบูต (main.py / worker.py)
    log = get_logger(__name__)

    with log_context(job_id="j-123"):     # ทุกบรรทัดในบล็อกนี้จะมี job_id ติดไปด้วย
        log.info("เริ่มประมวลผลใบเสร็จ")
"""
from __future__ import annotations

import json
import logging
import re
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Iterator
from urllib.parse import urlsplit

# ═══════════════════════════════════════════════════════════
# ส่วนที่ 1 — กฎการปิดบัง (pure function เทสได้โดยไม่ต้องมี logger)
# ═══════════════════════════════════════════════════════════

MASK = "***"

#: ชื่อ field/parameter ที่ห้ามให้ค่าโผล่ใน log เด็ดขาด
#: otp อยู่ในนี้ด้วย เพราะ OTP ดิบใน log = ยืมรหัสคนอื่นได้
SENSITIVE_KEYS = (
    "token",
    "access_token",
    "refresh_token",
    "password",
    "pwd",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "key",
    "authorization",
    "otp",
)

_KEYS_PATTERN = "|".join(SENSITIVE_KEYS)

#: รูปแบบ query string / kwargs — ครอบทั้ง "?token=abc" และ "token=abc"
_QUERY_PARAM_RE = re.compile(rf"\b({_KEYS_PATTERN})=([^&\s\"'}}\]]*)", re.IGNORECASE)

#: รูปแบบ JSON — "password": "abc"
_JSON_FIELD_RE = re.compile(rf'"({_KEYS_PATTERN})"\s*:\s*"([^"]*)"', re.IGNORECASE)

#: header แบบ Authorization: Bearer xxx
_BEARER_RE = re.compile(r"\b(bearer|basic)\s+[A-Za-z0-9._\-=/+]+", re.IGNORECASE)

#: เบอร์มือถือไทย (PDPA — เบอร์คือข้อมูลส่วนบุคคล ห้าม log เต็ม)
#: รับทั้ง 0812345678 และ +66812345678
_PHONE_RE = re.compile(r"\b(?:0|\+?66)[689]\d{8}\b")

#: เบอร์ที่ mask แล้วยังพอเอาไปเทียบกับเคสที่ลูกค้าแจ้งได้ แต่โทรออกไม่ได้
_PHONE_KEEP_HEAD = 3
_PHONE_KEEP_TAIL = 2


def _mask_phone(match: re.Match[str]) -> str:
    """0812345678 → 081*****78"""
    phone = match.group(0)
    hidden = len(phone) - _PHONE_KEEP_HEAD - _PHONE_KEEP_TAIL
    return phone[:_PHONE_KEEP_HEAD] + "*" * hidden + phone[-_PHONE_KEEP_TAIL:]


def mask_text(text: str) -> str:
    """ปิดบัง secret + เบอร์โทรในข้อความใดๆ

    ใช้กับ "บรรทัด log ที่ประกอบเสร็จแล้ว" เพื่อให้ครอบคลุมทุกทาง —
    ทั้งข้อความ, ค่า extra, และ traceback ที่บางทีแอบพก URL ติดมาด้วย
    """
    text = _QUERY_PARAM_RE.sub(rf"\1={MASK}", text)
    text = _JSON_FIELD_RE.sub(rf'"\1": "{MASK}"', text)
    text = _BEARER_RE.sub(rf"\1 {MASK}", text)
    return _PHONE_RE.sub(_mask_phone, text)


def safe_url(url: str) -> str:
    """ตัด query string ทิ้งทั้งก้อน เหลือแค่ scheme://host/path

    loga ยัด token/password/cuid ไว้ใน query string หมด → วิธีที่ปลอดภัยที่สุด
    คือไม่ log query เลย ไม่ใช่ไล่ mask ทีละตัว (ตัวที่ลืมคือตัวที่หลุด)

        >>> safe_url("https://api.loga.app/api/main/login?token=abc&password=x")
        'https://api.loga.app/api/main/login'
    """
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}" if parts.scheme else parts.path


# ═══════════════════════════════════════════════════════════
# ส่วนที่ 2 — บริบทที่ติดไปทุกบรรทัด (job_id / receipt_id / tenant_id)
# ═══════════════════════════════════════════════════════════

#: ใช้ ContextVar เพราะงานเราเป็น async + มี worker หลายตัว
#: ContextVar แยกค่าให้อัตโนมัติตาม task/thread — ตัวแปร global ธรรมดาจะปนกันข้ามงาน
_log_context: ContextVar[dict[str, Any]] = ContextVar("log_context", default={})


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    """ผูกค่าเข้ากับทุกบรรทัด log ที่เกิดในบล็อกนี้ (ซ้อนกันได้)

    มีไว้เพื่อ "ไล่ตามงานหนึ่งใบข้ามด่าน" ได้ — ไม่ต้องส่ง job_id ไปเป็น
    พารามิเตอร์ทุกฟังก์ชัน และไม่มีทางลืมใส่บางบรรทัด

        with log_context(job_id="j-1", receipt_id="r-9"):
            log.info("ocr เสร็จ")   # → {"job_id": "j-1", "receipt_id": "r-9", ...}
    """
    merged = {**_log_context.get(), **fields}
    token = _log_context.set(merged)
    try:
        yield
    finally:
        _log_context.reset(token)


# ═══════════════════════════════════════════════════════════
# ส่วนที่ 3 — formatter + setup
# ═══════════════════════════════════════════════════════════

#: attribute มาตรฐานของ LogRecord — อะไรที่ไม่อยู่ในนี้ถือว่าเป็น extra ที่คนเรียกใส่มาเอง
_RESERVED_RECORD_FIELDS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message", "module",
        "msecs", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "taskName", "thread", "threadName",
    }
)


class JsonLogFormatter(logging.Formatter):
    """แปลง log เป็น JSON บรรทัดเดียว แล้ว mask ก่อนปล่อยออก

    ทำไม JSON: log ของเราต้องค้นด้วย job_id/receipt_id ได้ (ดู docs/slo.md)
    ข้อความเปล่าๆ จะ grep ข้ามด่านไม่ได้ และเราจงใจไม่ใช้ OpenTelemetry เต็มระบบ
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            **_log_context.get(),
            **self._extra_fields(record),
        }

        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)

        line = json.dumps(payload, ensure_ascii=False, default=str)
        return mask_text(line)  # ← ตาข่ายชั้นสุดท้าย ทุกบรรทัดผ่านตรงนี้เสมอ

    @staticmethod
    def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
        """ดึงค่าที่คนเรียกใส่มาเอง เช่น log.info("...", extra={"status": 502})"""
        return {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_RECORD_FIELDS and not key.startswith("_")
        }


def _force_utf8_stdout() -> None:
    """บังคับ stdout เป็น UTF-8

    Windows console ดีฟอลต์เป็น cp874 → ข้อความไทยใน log จะกลายเป็นขยะอ่านไม่ออก
    ใช้ reconfigure เพราะแก้ที่ stream เดิม (ไม่สร้างตัวใหม่มาทับ) จึงเรียกซ้ำได้ไม่พัง
    บาง stream ไม่มี reconfigure เช่นตอน pytest capture — กรณีนั้นข้ามไป
    """
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")


def setup_logging(level: str = "INFO") -> None:
    """ตั้งค่า log ของทั้ง process — เรียกครั้งเดียวตอนบูต (เรียกซ้ำไม่พัง)

    ออกทาง stdout เพราะ docker-compose/VPS เก็บ log จาก stdout อยู่แล้ว
    (ยังไม่ต้องมี log shipper — ดู blueprint ส่วนที่ 3 ของที่ยังไม่ทำ)
    """
    _force_utf8_stdout()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())

    root = logging.getLogger()
    root.handlers.clear()  # กัน handler ซ้อนตอนเรียกซ้ำ (เทส/reload) → log จะไม่ออกซ้ำบรรทัด
    root.addHandler(handler)
    root.setLevel(level.upper())

    # uvicorn ตั้ง handler ของตัวเองไว้ ถ้าไม่ปิดจะมี log 2 รูปแบบปนกัน
    # และที่สำคัญ — ของ uvicorn ไม่ผ่าน mask ของเรา
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True


def _safe_extra_key(key: str) -> str:
    """เปลี่ยนชื่อ field ที่ชนกับ attribute ในตัวของ LogRecord โดยเติม _ ต่อท้าย

    ทำไมต้องมี: logging มาตรฐานจะ "โยน KeyError" ถ้า extra มี key ชื่อ msg/name/module/
    args ฯลฯ แปลว่าการเขียน log ผิดหนึ่งบรรทัดทำให้ระบบล้มได้จริง — ซึ่งรับไม่ได้
    ถ้าเกิดใน worker เราจะเสียใบเสร็จของลูกค้าไปเพราะ log บรรทัดเดียว

    (เจอของจริงตอนเขียน loga_client: log.warning(..., extra={"msg": ...}) → ระบบพัง)
    """
    return f"{key}_" if key in _RESERVED_RECORD_FIELDS else key


class _SafeExtraLogger(logging.Logger):
    """Logger ที่ extra ชนชื่อแล้วไม่ทำให้ระบบล้ม

    แก้ที่ makeRecord เพราะ error เกิดก่อนถึง formatter — formatter ช่วยไม่ได้
    """

    def makeRecord(self, name, level, fn, lno, msg, args, exc_info,
                   func=None, extra=None, sinfo=None):
        if extra:
            extra = {_safe_extra_key(key): value for key, value in extra.items()}
        return super().makeRecord(
            name, level, fn, lno, msg, args, exc_info, func, extra, sinfo
        )


def get_logger(name: str) -> logging.Logger:
    """ขอ logger ประจำไฟล์ — ใช้ get_logger(__name__) ทุกไฟล์

    ห่อ logging.getLogger ไว้เพื่อให้ทั้งระบบ import จากที่เดียว
    วันหน้าถ้าเปลี่ยนไปใช้ structlog แก้ที่นี่ที่เดียว ไฟล์อื่นไม่ต้องแตะ

    สลับคลาสเฉพาะตอนสร้าง logger ของเรา แล้วคืนค่าเดิมทันที — lib อื่น
    (uvicorn/httpx) ที่สร้าง logger ของตัวเองจะไม่ได้รับผลกระทบ
    """
    logging.setLoggerClass(_SafeExtraLogger)
    try:
        return logging.getLogger(name)
    finally:
        logging.setLoggerClass(logging.Logger)
