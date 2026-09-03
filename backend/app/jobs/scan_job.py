"""★ ตัวคุมทั้งสายของงานสแกน 1 ใบ — ที่ที่ทุกด่านมาต่อกัน

    โหลดรูป → OCR → แยกค่า → ★ กันใบซ้ำ → บันทึกใบเสร็จ → ส่งแต้มเข้า CRM → แจ้งลูกค้า

★ ไฟล์นี้คือสิ่งที่ Step 3 ตั้งใจพิสูจน์: สถาปัตยกรรม async job ใช้ได้จริง
  แล้ว Step 4-6 ค่อยเปลี่ยนของปลอมเป็นของจริงทีละชิ้นโดยไม่ต้องรื้อโครง — ซึ่งเป็นจริง

จะถูกเสียบเพิ่มในขั้นถัดไป (จุดที่เว้นไว้ชัดเจน):
    Step 5 — หาว่าร้านอะไร + ใช้ template ดึงค่า (merchant_resolver/template_matcher)
    Step 6 — retry / dead letter / Excel fallback ตอน CRM ล่ม

★ กฎเหล็ก: ไม่ว่าอะไรพัง worker ต้องไม่ตาย — ทุก error ถูกจับ แปลงเป็นสถานะงาน
  และข้อความที่ลูกค้าอ่านรู้เรื่อง (ใบเสร็จหายไปเงียบๆ คือสิ่งที่ยอมรับไม่ได้ที่สุด)

★ ลำดับใน _process มีเหตุผล ห้ามสลับ:
  กันใบซ้ำ → บันทึกแถว → ส่งแต้ม
  ถ้าส่งแต้มก่อนบันทึก ช่วงที่ระบบล่มพอดีจะไม่มีร่องรอยว่าเคยให้แต้มใบนี้ไปแล้ว
"""
from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.members import Member
from app.database.receipts import (
    STATUS_AWARDED, STATUS_FAILED, STATUS_PENDING, ReceiptRecord,
)
from app.external.notifier_interface import NotifierPort
from app.image_prep.image_pipeline import prepare_for_ocr
from app.jobs.job_queue import ScanJob
from app.jobs.job_status import JobState, JobStatusStore
from app.observability.logging import get_logger, log_context
from app.ocr.ocr_interface import OcrEngine
from app.points.point_rate import points_for
from app.points.point_service import PointService
from app.receipt_check.duplicate_check import find_duplicate
from app.receipt_data.field_extractor import extract_receipt_fields
from app.receipt_data.receipt_identity import content_fingerprint, image_fingerprint
from app.receipt_data.receipt_schema import Receipt
from app.reliability.errors import DuplicateReceiptError, GetpointError, InputValidationError
from app.storage.image_store import ImageStore
from app.storage.ocr_text_store import OcrTextStore

log = get_logger(__name__)

#: ข้อความแจ้งลูกค้าเมื่อสำเร็จ — ลูกค้าเห็นใน LINE
_SUCCESS_MESSAGE = (
    "🎉 บันทึกใบเสร็จเรียบร้อย!\nร้าน {merchant}\nยอด {amount:,.2f} บาท\nได้รับ {points:,} แต้ม"
)
_SUCCESS_WITH_BALANCE = "\nแต้มสะสมของคุณตอนนี้ {balance:,} แต้ม"

#: ข้อความเมื่อพัง — ต้องบอก "ต้องทำอะไรต่อ" ไม่ใช่แค่บอกว่าพัง
_FAILURE_PREFIX = "😕 ขออภัย เราบันทึกใบเสร็จนี้ไม่สำเร็จ\n"
_GENERIC_FAILURE = "เกิดข้อผิดพลาดชั่วคราว กรุณาลองส่งใหม่อีกครั้ง"

#: ★ ข้อความเมื่อเจอใบซ้ำ — บอก "เกิดอะไรขึ้น" ไม่ใช่ "คุณทำผิด"
#:   ลูกค้าส่วนใหญ่ที่ส่งซ้ำคือกดพลาด/ไม่แน่ใจว่าส่งไปแล้ว ไม่ใช่คนตั้งใจโกง
_DUPLICATE_MESSAGE = "ใบเสร็จนี้เคยใช้รับแต้มไปแล้ว จึงรับแต้มซ้ำไม่ได้"

#: คำนำหน้าของ reference ที่ส่งให้ CRM — มีไว้ให้แยกออกจากเลขอ้างอิงชนิดอื่นในระบบ CRM
_CRM_REFERENCE_PREFIX = "gp"


def _crm_reference_for(receipt_row_id: int) -> str:
    return f"{_CRM_REFERENCE_PREFIX}{receipt_row_id}"


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
        ocr_text_store: OcrTextStore | None = None,
    ) -> None:
        self._images = image_store
        self._ocr = ocr
        self._points = points
        self._notifier = notifier
        self._status = status_store
        #: เก็บข้อความ OCR ดิบไว้ audit/debug — ไม่มีก็ทำงานได้ (ข้อมูลเสริม)
        self._ocr_text = ocr_text_store

    def run(self, session: Session, job: ScanJob) -> None:
        """ทำงาน 1 ใบให้จบ — ไม่โยน exception ออกไป (worker ต้องไม่ตายเพราะงานใบเดียว)"""
        with log_context(job_id=job.job_id, receipt_id=job.receipt_id, tenant_id=job.tenant_id):
            try:
                self._status.mark(job.job_id, JobState.PROCESSING)
                self._process(session, job)

            except DuplicateReceiptError as exc:
                # ★ ไม่ใช่ความผิดพลาด — เป็นผลลัพธ์ที่ระบบตั้งใจให้เกิด
                #   แยก log ออกจากกรณีอื่นเพื่อให้ดูสถิติ "ใบซ้ำ" แยกจาก "อ่านไม่ออก" ได้
                log.info("ปฏิเสธเพราะใบซ้ำ", extra={"reason": exc.reason})
                self._fail(session, job, str(exc))

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
        # ตัดพื้นหลัง → ดัดเอียง → ปรับความคมชัด · รูปที่เบลอ/มืดเกินถูกตีกลับตรงนี้
        # (วัดจริงแล้วช่วยทั้งความแม่นและความเร็ว — ดู docs/decisions/0005)
        prepared = prepare_for_ocr(image)

        ocr_result = self._ocr.read(prepared)
        self._save_ocr_text(job, ocr_result)
        fields = extract_receipt_fields(ocr_result)

        receipt = Receipt(
            tenant_id=job.tenant_id,
            merchant=fields["merchant"],
            merchant_code=fields["merchant_code"],
            receipt_no=fields["receipt_no"],
            receipt_date=fields["receipt_date"],
            receipt_time=fields["receipt_time"],
            reference_codes=fields["reference_codes"],
            total_amount=fields["total_amount"],
            source_image_id=job.image_key,
        )

        # ★ ด่านกันแต้มซ้ำ — ต้องอยู่ "ก่อน" ส่งแต้มเสมอ
        #   ตัดสินจากประวัติใบเสร็จที่เคยรับไว้ ไม่ใช่จากแฮชค่าเดียว (ดู duplicate_check)
        # ★ บันทึกแถวก่อนส่งแต้ม แล้วค่อยอัปเดตผล
        #   ถ้าระบบล่มระหว่างส่ง แถวยังอยู่ → รอบหน้า duplicate_check จะเจอและไม่ให้แต้มซ้ำ
        #   (ถ้าบันทึกหลังส่งสำเร็จ ช่วงที่ล่มพอดีจะกลายเป็นช่องให้ได้แต้มสองเท่า)
        record = self._resolve_receipt_row(session, job, receipt, member=member, image=image)

        # reference = id ของแถวนี้ ไม่ใช่แฮชเนื้อหา — ยิงซ้ำแถวเดิมได้ค่าเดิม CRM จึงไม่
        # บันทึกซ้ำ (ADR 0003 #7) แต่ใบคนละใบที่เนื้อหาบังเอิญคล้ายกันจะไม่ชนกัน (ADR 0006)
        reference = record.crm_reference or _crm_reference_for(record.id)
        strategy = self._points.strategy_for(receipt)
        try:
            award = strategy.award(receipt, customer_id=member.crm_customer_id, reference=reference)
        except GetpointError:
            # ★ ส่งไม่สำเร็จ = ยังไม่ได้แต้ม → ทำเครื่องหมายไว้ให้ลูกค้าส่งใหม่ได้
            #   ถ้าปล่อยเป็น PENDING ไว้เฉยๆ รอบหน้าจะถูกมองว่า "ใบซ้ำ" แล้วลูกค้า
            #   จะไม่มีวันได้แต้มของใบนี้เลย — พังแบบเงียบที่สุด
            record.status = STATUS_FAILED
            record.crm_reference = reference   # จำ reference ไว้ ส่งซ้ำจะได้ไม่ได้แต้มสองรอบ
            session.commit()
            raise

        expected_points = points_for(receipt.total_amount)
        record.status = STATUS_AWARDED
        record.crm_reference = reference
        record.points_awarded = expected_points
        session.commit()

        self._status.mark(
            job.job_id, JobState.SUCCEEDED, points_balance=award.points_balance
        )
        self._notify_success(member, receipt, expected_points, award.points_balance)
        log.info(
            "สแกนสำเร็จ",
            extra={
                "amount": receipt.total_amount,
                "points": expected_points,
                "reference": reference,
            },
        )

    def _resolve_receipt_row(
        self, session: Session, job: ScanJob, receipt: Receipt, *, member: Member, image: bytes
    ) -> ReceiptRecord:
        """หาแถวใบเสร็จที่จะใช้กับงานนี้ — เจอของเดิมก็ใช้ต่อ ไม่เจอก็สร้างใหม่

        ★ ตรรกะสำคัญ: "ใบซ้ำ" กับ "ใบเดิมที่ยังส่งแต้มไม่สำเร็จ" ต่างกันโดยสิ้นเชิง
            เคยได้แต้มแล้ว  → ปฏิเสธ (นี่คือการกันแต้มซ้ำจริงๆ)
            ยังไม่ได้แต้ม   → ใช้แถวเดิมส่งใหม่ด้วย reference เดิม
                              (ลูกค้าส่งซ้ำหลัง CRM ล่ม ต้องได้แต้ม ไม่ใช่โดนบล็อก)
        """
        verdict = find_duplicate(session, receipt, member_id=member.id)
        if verdict.is_duplicate and verdict.existing is not None:
            if verdict.existing.status == STATUS_AWARDED:
                raise DuplicateReceiptError(_DUPLICATE_MESSAGE, reason=verdict.reason)
            log.info("ใบเดิมที่ยังส่งแต้มไม่สำเร็จ — ส่งซ้ำด้วย reference เดิม")
            return verdict.existing

        return self._save_receipt(session, job, receipt, member_id=member.id, image=image)

    def _save_receipt(
        self, session: Session, job: ScanJob, receipt: Receipt, *, member_id: int, image: bytes
    ) -> ReceiptRecord:
        """เขียนแถวใบเสร็จสถานะ PENDING แล้วคืนแถวที่มี id แล้ว

        คำนวณลายนิ้วมือรูปที่นี่ (ไม่ส่งมาในใบสั่งงาน) เพื่อไม่ต้องแก้รูปแบบข้อความในคิว
        — งานที่ค้างอยู่ในคิวตอน deploy จะอ่านไม่ออกทันทีถ้าเพิ่ม field ใหม่เข้าไป
        """
        record = ReceiptRecord(
            tenant_id=job.tenant_id,
            member_id=member_id,
            content_fingerprint=content_fingerprint(
                job.tenant_id,
                reference_codes=receipt.reference_codes,
                receipt_no=receipt.receipt_no,
                receipt_date=receipt.receipt_date,
                total_amount=receipt.total_amount,
            ),
            image_fingerprint=image_fingerprint(job.tenant_id, image),
            merchant=receipt.merchant,
            merchant_code=receipt.merchant_code,
            receipt_no=receipt.receipt_no,
            receipt_date=receipt.receipt_date,
            receipt_time=receipt.receipt_time,
            total_amount=receipt.total_amount,
            reference_codes=receipt.reference_codes,
            status=STATUS_PENDING,
            source_image_id=receipt.source_image_id,
        )
        session.add(record)
        try:
            # ★ commit ตรงนี้เลย ไม่ใช่รอจนจบงาน
            #   worker เปิด session ใหม่ต่อ 1 งานและปิดโดยไม่ commit เมื่อพัง (ดู worker.py)
            #   ถ้าไม่ commit ตอนนี้ แล้วโค้ดพังหลังส่งแต้มสำเร็จ แถวนี้จะหายไปทั้งแถว
            #   → ลูกค้าส่งใหม่แล้วได้แต้มอีกรอบ ทั้งที่แต้มรอบแรกเข้าไปแล้ว
            #   ชน unique constraint ก็รู้ตรงนี้ (worker อีกตัวเขียนใบเดียวกันแทรกเข้ามา)
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            log.info("ชน unique constraint ของใบเสร็จ (มีตัวอื่นเขียนแทรก)")
            raise DuplicateReceiptError(_DUPLICATE_MESSAGE, reason="ลายนิ้วมือเนื้อหาซ้ำ") from exc
        return record

    def _save_ocr_text(self, job: ScanJob, ocr_result) -> None:
        """เก็บข้อความ OCR ดิบไว้ audit — ★ ล้มแล้วห้ามล้มงาน (เป็นข้อมูลเสริม)

        ถ้าเก็บไม่ได้ (ดิสก์เต็ม ฯลฯ) การให้แต้มต้องเดินต่อได้ตามปกติ
        """
        if self._ocr_text is None:
            return
        try:
            self._ocr_text.put(job.tenant_id, job.receipt_id, ocr_result.lines())
        except Exception as exc:  # noqa: BLE001
            log.warning("เก็บข้อความ OCR ไม่สำเร็จ (ข้ามไป)", extra={"detail": str(exc)})

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

    def _notify_success(
        self, member: Member, receipt: Receipt, points: int, balance: int | None
    ) -> None:
        message = _SUCCESS_MESSAGE.format(
            merchant=receipt.merchant, amount=receipt.total_amount, points=points
        )
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
