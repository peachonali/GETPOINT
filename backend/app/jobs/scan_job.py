"""★ ตัวคุมทั้งสายของงานสแกน 1 ใบ — ที่ที่ทุกด่านมาต่อกัน

    โหลดรูป → OCR → แยกค่า → ลายนิ้วมือใบเสร็จ → ส่งแต้มเข้า CRM → แจ้งลูกค้าทาง LINE

★ ไฟล์นี้คือสิ่งที่ Step 3 ตั้งใจพิสูจน์: สถาปัตยกรรม async job ใช้ได้จริง
  ตอนนี้ OCR เป็นของปลอม แต่เส้นทางทั้งหมดเป็นของจริง — Step 4-6 แค่เปลี่ยนของปลอม
  เป็นของจริงทีละชิ้น โดยไม่ต้องรื้อโครง

จะถูกเสียบเพิ่มในขั้นถัดไป (จุดที่เว้นไว้ชัดเจน):
    Step 4 — OpenCV เตรียมรูปก่อน OCR (image_pipeline)
    Step 5 — หาว่าร้านอะไร + ใช้ template ดึงค่า (merchant_resolver/template_matcher)
    Step 6 — เช็คใบซ้ำก่อนให้แต้ม (duplicate_check) + retry/dead letter

★ กฎเหล็ก: ไม่ว่าอะไรพัง worker ต้องไม่ตาย — ทุก error ถูกจับ แปลงเป็นสถานะงาน
  และข้อความที่ลูกค้าอ่านรู้เรื่อง (ใบเสร็จหายไปเงียบๆ คือสิ่งที่ยอมรับไม่ได้ที่สุด)
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.database.members import Member
from app.external.notifier_interface import NotifierPort
from app.jobs.job_queue import ScanJob
from app.jobs.job_status import JobState, JobStatusStore
from app.observability.logging import get_logger, log_context
from app.ocr.ocr_interface import OcrEngine
from app.points.point_service import PointService
from app.receipt_data.field_extractor import extract_receipt_fields
from app.receipt_data.receipt_identity import receipt_fingerprint
from app.receipt_data.receipt_schema import Receipt
from app.reliability.errors import GetpointError, InputValidationError
from app.storage.image_store import ImageStore

log = get_logger(__name__)

#: ข้อความแจ้งลูกค้าเมื่อสำเร็จ — ลูกค้าเห็นใน LINE
_SUCCESS_MESSAGE = "🎉 บันทึกใบเสร็จเรียบร้อย!\nร้าน {merchant}\nยอด {amount:,.2f} บาท"
_SUCCESS_WITH_BALANCE = "\nแต้มสะสมของคุณตอนนี้ {balance:,} แต้ม"

#: ข้อความเมื่อพัง — ต้องบอก "ต้องทำอะไรต่อ" ไม่ใช่แค่บอกว่าพัง
_FAILURE_PREFIX = "😕 ขออภัย เราบันทึกใบเสร็จนี้ไม่สำเร็จ\n"
_GENERIC_FAILURE = "เกิดข้อผิดพลาดชั่วคราว กรุณาลองส่งใหม่อีกครั้ง"


class ScanJobRunner:
    """ประกอบ dependency ครั้งเดียวตอนบูต แล้วใช้ซ้ำกับทุกงาน (ดู worker.py)"""

    def __init__(
        self,
        *,
        image_store: ImageStore,
        ocr: OcrEngine,
        points: PointService,
        notifier: NotifierPort,
        status_store: JobStatusStore,
    ) -> None:
        self._images = image_store
        self._ocr = ocr
        self._points = points
        self._notifier = notifier
        self._status = status_store

    def run(self, session: Session, job: ScanJob) -> None:
        """ทำงาน 1 ใบให้จบ — ไม่โยน exception ออกไป (worker ต้องไม่ตายเพราะงานใบเดียว)"""
        with log_context(job_id=job.job_id, receipt_id=job.receipt_id, tenant_id=job.tenant_id):
            try:
                self._status.mark(job.job_id, JobState.PROCESSING)
                self._process(session, job)

            except InputValidationError as exc:
                # ปัญหาที่ลูกค้าแก้เองได้ (รูปเบลอ/อ่านยอดไม่ออก) — บอกตรงๆ ว่าให้ทำอะไร
                log.info("งานสแกนไม่ผ่านการตรวจ", extra={"detail": str(exc)})
                self._fail(session, job, str(exc))

            except GetpointError as exc:
                # ปัญหาฝั่งระบบ (CRM ล่ม ฯลฯ) — ไม่บอกรายละเอียดภายในให้ลูกค้า
                log.warning("งานสแกนล้มเหลว", extra={"detail": str(exc)})
                self._fail(session, job, _GENERIC_FAILURE)

            except Exception as exc:  # noqa: BLE001 — ตาข่ายสุดท้าย ห้าม worker ตาย
                log.exception("งานสแกนพังแบบไม่คาดคิด", extra={"detail": str(exc)})
                self._fail(session, job, _GENERIC_FAILURE)

    # ═══════════════════════════════════════════
    # เส้นทางหลัก
    # ═══════════════════════════════════════════

    def _process(self, session: Session, job: ScanJob) -> None:
        member = self._load_member(session, job)

        image = self._images.get(job.tenant_id, job.receipt_id)
        # TODO(Step 4): image = image_pipeline.prepare(image)  ← OpenCV crop/deskew/enhance

        ocr_result = self._ocr.read(image)
        # TODO(Step 5): merchant_resolver + template_matcher แทน extract_receipt_fields
        fields = extract_receipt_fields(ocr_result)

        receipt = Receipt(
            tenant_id=job.tenant_id,
            merchant=fields["merchant"],
            receipt_no=fields["receipt_no"],
            receipt_date=fields["receipt_date"],
            total_amount=fields["total_amount"],
            source_image_id=job.image_key,
        )

        # ลายนิ้วมือใบเสร็จ = reference ที่ส่งให้ CRM → ยิงซ้ำก็ไม่ได้แต้มซ้ำ (ADR 0003 #7)
        reference = receipt_fingerprint(
            job.tenant_id,
            merchant=receipt.merchant,
            receipt_no=receipt.receipt_no,
            receipt_date=receipt.receipt_date,
            total_amount=receipt.total_amount,
        )
        # TODO(Step 6): duplicate_check(reference) ก่อนส่ง — ตอนนี้พึ่ง idempotency ของ CRM

        strategy = self._points.strategy_for(receipt)
        award = strategy.award(receipt, customer_id=member.crm_customer_id, reference=reference)

        self._status.mark(
            job.job_id, JobState.SUCCEEDED, points_balance=award.points_balance
        )
        self._notify_success(member, receipt, award.points_balance)
        log.info("สแกนสำเร็จ", extra={"amount": receipt.total_amount, "reference": reference})

    @staticmethod
    def _load_member(session: Session, job: ScanJob) -> Member:
        """หาสมาชิก + ยืนยันว่าผูก CRM แล้ว (ยังไม่ผูก = ยังรับแต้มไม่ได้)"""
        member = session.get(Member, job.member_id)
        if member is None:
            raise InputValidationError("ไม่พบข้อมูลสมาชิก กรุณาลงทะเบียนใหม่")
        if not member.crm_customer_id:
            raise InputValidationError("กรุณายืนยันเบอร์โทรก่อนรับแต้ม")
        return member

    # ═══════════════════════════════════════════
    # แจ้งลูกค้า
    # ═══════════════════════════════════════════

    def _notify_success(self, member: Member, receipt: Receipt, balance: int | None) -> None:
        message = _SUCCESS_MESSAGE.format(merchant=receipt.merchant, amount=receipt.total_amount)
        if balance is not None:
            message += _SUCCESS_WITH_BALANCE.format(balance=balance)
        self._notify(member, message)

    def _fail(self, session: Session, job: ScanJob, customer_message: str) -> None:
        """บันทึกว่าล้มเหลว + บอกลูกค้า — ตัวนี้ห้ามโยน error ต่อเด็ดขาด"""
        self._status.mark(job.job_id, JobState.FAILED, message=customer_message)

        member = session.get(Member, job.member_id)
        if member is not None:
            self._notify(member, _FAILURE_PREFIX + customer_message)

    def _notify(self, member: Member, message: str) -> None:
        """ส่งข้อความหาลูกค้า — ส่งไม่ได้ก็ไม่ให้ล้มทั้งงาน (แต้มเข้าไปแล้วสำคัญกว่า)"""
        try:
            self._notifier.notify(member.line_user_id, message)
        except Exception as exc:  # noqa: BLE001
            log.warning("แจ้งเตือนลูกค้าไม่สำเร็จ", extra={"detail": str(exc)})
