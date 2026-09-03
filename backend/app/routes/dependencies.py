"""ตัวดึง component ที่ประกอบไว้ใน app.state — ประกาศที่เดียวสำหรับทุก route

★ ทำไมต้องรวมไว้ที่เดียว:
    FastAPI จับคู่ dependency override ด้วย "ตัวฟังก์ชัน" ไม่ใช่ชื่อ
    ถ้าสอง route ประกาศ get_job_status() ของตัวเองที่หน้าตาเหมือนกัน มันคือคนละตัว
    → เทส override ตัวหนึ่ง อีกตัวยังไปดึงของจริงอยู่ แล้วพังแบบงงๆ
    (เจอจริงตอนเขียนเทส /jobs — จึงย้ายมารวมที่นี่)
"""
from __future__ import annotations

from fastapi import Request

from app.external.crm_interface import CrmPort
from app.jobs.job_queue import JobQueue
from app.jobs.job_status import JobStatusStore
from app.member.member_service import MemberService
from app.reliability.idempotency import IdempotencyStore
from app.security.auth_guard import LineTokenVerifier
from app.security.rate_limit import RateLimiter
from app.storage.image_store import ImageStore


def get_member_service(request: Request) -> MemberService:
    return request.app.state.member_service


def get_line_verifier(request: Request) -> LineTokenVerifier:
    return request.app.state.line_verifier


def get_tenant_id(request: Request) -> str:
    return request.app.state.default_tenant_id


def get_image_store(request: Request) -> ImageStore:
    return request.app.state.image_store


def get_job_queue(request: Request) -> JobQueue:
    return request.app.state.job_queue


def get_job_status(request: Request) -> JobStatusStore:
    return request.app.state.job_status


def get_scan_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.scan_rate_limiter


def get_formula_id(request: Request) -> str:
    """formula_id ปัจจุบัน — Excel export ต้องใส่ในไฟล์เพื่อให้อัปโหลดกลับ loga ได้"""
    return request.app.state.formula_id


def get_admin_token(request: Request) -> str:
    """โทเคนแอดมินที่ตั้งไว้ (ว่าง = ปิดหน้า admin) — แยกเป็น dependency ให้เทส override ได้"""
    return request.app.state.admin_token


def get_crm(request: Request) -> CrmPort:
    return request.app.state.crm


def get_idempotency_store(request: Request) -> IdempotencyStore:
    return request.app.state.idempotency
