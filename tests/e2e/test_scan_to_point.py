"""★ เทสทั้งเส้น: รูปใบเสร็จ → OCR → แยกค่า → แต้มเข้า CRM → แจ้งลูกค้า

นี่คือเป้าหมายของ Step 3 — พิสูจน์ว่าสถาปัตยกรรมทั้งหมดต่อกันได้จริง
ใช้ของปลอมเฉพาะ "ปลายทางที่อยู่นอกระบบเรา" (OCR/CRM/LINE/Redis)
ส่วนตรรกะทั้งหมดตรงกลางเป็นของจริง — เทสนี้จึงพังจริงถ้า pipeline พัง
"""
import cv2
import fakeredis
import numpy as np
import pytest
from sqlalchemy.orm import Session

from app.database.members import Member
from app.database.receipts import STATUS_AWARDED, STATUS_FAILED, ReceiptRecord
from app.external.fake_loga import FakeLoga
from app.external.fake_notifier import FakeNotifier
from app.jobs.job_queue import JobQueue, ScanJob
from app.jobs.job_status import JobState, JobStatusStore
from app.jobs.scan_job import ScanJobRunner
from app.ocr.fake_ocr import FakeOcr
from app.points.crm_formula_strategy import CrmFormulaStrategy
from app.points.point_service import PointService
from app.reliability.errors import ExternalServiceError
from app.storage.image_store import ImageStore
from app.storage.local_storage import LocalStorage
from app.storage.ocr_text_store import OcrTextStore

TENANT = "v-club"
LINE_USER = "U-line-1"
PHONE = "0812345678"
RECEIPT_ID = "rcp-001"


def _receipt_photo() -> bytes:
    """รูปใบเสร็จจริงๆ (สังเคราะห์) — ต้องเป็นรูปที่ decode ได้จริง
    เพราะ pipeline มี image_prep (OpenCV) ที่จะตีกลับไฟล์ที่ไม่ใช่รูป"""
    image = np.full((760, 460, 3), 245, np.uint8)
    for index, text in enumerate(["TEST SHOP", "TOTAL 250.00"]):
        cv2.putText(image, text, (28, 120 + index * 260), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (15, 15, 15), 2)
    return cv2.imencode(".jpg", image)[1].tobytes()


IMAGE = _receipt_photo()


@pytest.fixture
def world(db_session, tmp_path):
    """ประกอบระบบทั้งชุด — ของจริงตรงกลาง ของปลอมเฉพาะปลายทางภายนอก"""
    redis = fakeredis.FakeStrictRedis(decode_responses=True)
    loga = FakeLoga()
    notifier = FakeNotifier()
    ocr = FakeOcr()
    status_store = JobStatusStore(redis)

    # สมาชิกที่ยืนยันเบอร์ + ผูก CRM แล้ว (ผ่าน Step 2 มาแล้ว)
    crm_customer = loga.seed_customer(PHONE, points=100)
    member = Member(
        tenant_id=TENANT, line_user_id=LINE_USER, phone=PHONE,
        phone_verified=True, crm_customer_id=crm_customer.customer_id,
    )
    db_session.add(member)
    db_session.commit()

    # รูปถูกเก็บไว้แล้วตอน web รับอัปโหลด
    images = ImageStore(LocalStorage(tmp_path / "storage"))
    image_key = images.put(TENANT, RECEIPT_ID, IMAGE)

    ocr_text = OcrTextStore(LocalStorage(tmp_path / "storage"))
    runner = ScanJobRunner(
        image_store=images,
        ocr=ocr,
        points=PointService(CrmFormulaStrategy(loga, formula_id="7")),
        notifier=notifier,
        status_store=status_store,
        ocr_text_store=ocr_text,
    )
    job = ScanJob(
        job_id="job-1", tenant_id=TENANT, member_id=member.id,
        receipt_id=RECEIPT_ID, image_key=image_key,
    )

    return {
        "runner": runner, "job": job, "session": db_session, "redis": redis,
        "loga": loga, "notifier": notifier, "ocr": ocr, "status": status_store,
        "member": member, "ocr_text": ocr_text,
    }


# ═══════════════════════════════════════════
# ★ เส้นทางหลัก — สแกนสำเร็จ
# ═══════════════════════════════════════════

def test_scan_to_point(world):
    """หัวใจของ Step 3: ส่งใบเสร็จ 1 ใบ → แต้มเข้า CRM → ลูกค้าได้รับแจ้ง"""
    world["runner"].run(world["session"], world["job"])

    # 1) OCR ถูกเรียกจริง
    assert world["ocr"].calls == 1

    # 2) แต้มถูกส่งเข้า CRM ด้วยยอดจากใบเสร็จ (FakeOcr คืนยอด 250.00)
    assert len(world["loga"].awards) == 1
    assert world["loga"].find_customer(PHONE).points_balance == 110  # 100 เดิม + floor(250/25)

    # 3) สถานะงานเป็นสำเร็จ
    status = world["status"].get("job-1")
    assert status.state is JobState.SUCCEEDED
    assert status.points_balance == 110

    # 4) ลูกค้าได้รับ LINE แจ้งผล
    assert len(world["notifier"].sent) == 1
    user_id, message = world["notifier"].sent[0]
    assert user_id == LINE_USER
    assert "250" in message


def test_reference_prevents_double_points(world):
    """ใบเดียวกันถูกประมวลผลซ้ำ (worker ทำซ้ำ/ลูกค้าส่งซ้ำ) → ต้องไม่ได้แต้มสองเท่า
    ★ นี่คือการพิสูจน์ว่าการกันแต้มซ้ำทำงานจริงทั้งสาย"""
    world["runner"].run(world["session"], world["job"])
    balance_after_first = world["loga"].find_customer(PHONE).points_balance

    world["runner"].run(world["session"], world["job"])  # รอบสอง

    assert world["loga"].find_customer(PHONE).points_balance == balance_after_first
    assert len(world["loga"].awards) == 1, "CRM ต้องบันทึกรายการเดียว"


# ═══════════════════════════════════════════
# ★ ด่านกันใบซ้ำ — ต่อกับ scan_job จริงไหม
# ═══════════════════════════════════════════

def test_receipt_row_is_written_before_points_are_sent(world):
    """ต้องมีร่องรอยในฐานข้อมูลเสมอว่าเคยรับใบนี้ไปแล้ว

    ★ ก่อนหน้านี้ระบบไม่เคยจำอะไรเลย → ต่อให้คำนวณลายนิ้วมือแม่นแค่ไหน
      ก็ไม่มีอะไรให้เทียบ → กันใบซ้ำไม่ได้เลย
    """
    world["runner"].run(world["session"], world["job"])

    rows = world["session"].query(ReceiptRecord).all()
    assert len(rows) == 1
    assert rows[0].status == STATUS_AWARDED
    assert rows[0].total_amount == 250.0
    assert rows[0].crm_reference, "ต้องจำ reference ที่ส่งให้ CRM ไว้"


def test_receipt_row_survives_a_crash_after_points_were_sent(world, db_engine):
    """★★ แต้มออกไปแล้ว แต่โค้ดพังก่อนงานจบ → แถวใบเสร็จต้องยังอยู่

    worker ของจริงเปิด session ใหม่ต่อ 1 งาน แล้วปิดทิ้งโดยไม่ commit เมื่อพัง
    ถ้าแถวใบเสร็จยังไม่ถูก commit ตอนนั้น มันจะหายไปทั้งแถว
    → ลูกค้าส่งใหม่แล้วได้แต้มอีกรอบ ทั้งที่แต้มรอบแรกเข้าไปแล้ว = ให้แต้มสองเท่า

    เทสนี้เกิดจากการทดลองทำลายโค้ด: เปลี่ยน commit เป็น flush แล้วเทสยังเขียวหมด
    เพราะเทสเดิมใช้ session เดียวตลอด จึงมองไม่เห็นว่าแถวไม่ได้ถูก commit
    """
    def award_then_crash(**kwargs):
        world["loga"].awards.append(kwargs)
        raise RuntimeError("พังหลังแต้มออกไปแล้ว")

    world["loga"].add_points = award_then_crash
    world["runner"].run(world["session"], world["job"])   # worker ต้องไม่ตาย

    # session ตัวใหม่ = มองเห็นเฉพาะสิ่งที่ commit ลงฐานข้อมูลจริงแล้วเท่านั้น
    with Session(db_engine) as fresh:
        rows = fresh.query(ReceiptRecord).all()
    assert len(rows) == 1, "แถวใบเสร็จต้องอยู่รอด ไม่งั้นส่งใหม่จะได้แต้มซ้ำ"


def test_duplicate_receipt_tells_customer_why(world):
    """ส่งซ้ำแล้วต้องได้ข้อความที่อ่านรู้เรื่อง ไม่ใช่ "เกิดข้อผิดพลาด" ลอยๆ"""
    world["runner"].run(world["session"], world["job"])
    world["notifier"].sent.clear()

    world["runner"].run(world["session"], world["job"])

    assert world["status"].get("job-1").state is JobState.FAILED
    assert "เคยใช้รับแต้มไปแล้ว" in world["status"].get("job-1").message
    assert world["notifier"].sent, "ต้องแจ้งลูกค้าว่าเกิดอะไรขึ้น"
    assert world["session"].query(ReceiptRecord).count() == 1, "ห้ามเขียนแถวซ้ำ"


def test_customer_can_retry_after_crm_failure(world):
    """★ CRM ล่มรอบแรก → ลูกค้าส่งใหม่ต้องได้แต้ม ไม่ใช่โดนบล็อกว่า "ใบซ้ำ"

    นี่คือกับดักที่ตามมาจากการบันทึกใบเสร็จก่อนส่งแต้ม:
    ถ้าแถวที่ส่งไม่สำเร็จไปบล็อกการส่งใหม่ ลูกค้าจะไม่มีวันได้แต้มของใบนี้เลย
    """
    def boom(**kwargs):
        raise ExternalServiceError("crm", "CRM ล่ม")

    original = world["loga"].add_points
    world["loga"].add_points = boom
    world["runner"].run(world["session"], world["job"])
    assert world["session"].query(ReceiptRecord).one().status == STATUS_FAILED

    world["loga"].add_points = original          # CRM กลับมาแล้ว
    world["runner"].run(world["session"], world["job"])

    assert len(world["loga"].awards) == 1, "ต้องได้แต้ม"
    assert world["status"].get("job-1").state is JobState.SUCCEEDED
    rows = world["session"].query(ReceiptRecord).all()
    assert len(rows) == 1, "ต้องใช้แถวเดิม ไม่สร้างแถวใหม่"
    assert rows[0].status == STATUS_AWARDED


def test_points_are_reported_to_customer(world):
    """ลูกค้าต้องรู้ว่าใบนี้ได้กี่แต้ม (250 บาท ÷ 100 = 2 แต้ม)"""
    world["runner"].run(world["session"], world["job"])

    _user_id, message = world["notifier"].sent[0]
    assert "2 แต้ม" in message
    assert world["session"].query(ReceiptRecord).one().points_awarded == 2


def test_ocr_text_saved_for_audit(world):
    """★ ข้อความ OCR ดิบถูกเก็บไว้ audit — เปิดดูย้อนหลังได้ว่าระบบอ่านอะไรมา"""
    world["runner"].run(world["session"], world["job"])

    saved = world["ocr_text"].get(TENANT, RECEIPT_ID)
    assert saved, "ต้องมีข้อความ OCR เก็บไว้"
    assert any("250" in line for line in saved)


# ═══════════════════════════════════════════
# เส้นทางล้มเหลว — ต้องไม่เงียบหาย
# ═══════════════════════════════════════════

def test_unreadable_receipt_fails_gracefully(world):
    """OCR อ่านยอดไม่ได้ → ไม่ให้แต้ม + บอกลูกค้าให้ถ่ายใหม่ (ไม่ใช่เงียบหาย)"""
    world["runner"]._ocr = FakeOcr(lines=[("อ่านอะไรไม่ออกเลย", (0, 0, 10, 10))])

    world["runner"].run(world["session"], world["job"])

    assert len(world["loga"].awards) == 0, "อ่านยอดไม่ได้ ห้ามให้แต้ม"
    status = world["status"].get("job-1")
    assert status.state is JobState.FAILED
    assert "ถ่าย" in status.message, "ต้องบอกลูกค้าว่าต้องทำอะไรต่อ"
    assert world["notifier"].sent, "ต้องแจ้งลูกค้าแม้ล้มเหลว"


def test_member_without_crm_link_cannot_earn(world):
    """ยังไม่ยืนยันเบอร์/ยังไม่ผูก CRM = ยังรับแต้มไม่ได้ (กฎธุรกิจของ UX แบบผสม)"""
    world["member"].crm_customer_id = None
    world["session"].commit()

    world["runner"].run(world["session"], world["job"])

    assert len(world["loga"].awards) == 0
    assert world["status"].get("job-1").state is JobState.FAILED


def test_crm_failure_does_not_kill_worker(world):
    """CRM ล่ม → งานล้มเหลวอย่างสุภาพ ไม่โยน exception ออกมาทำ worker ตาย"""
    def boom(**kwargs):
        raise RuntimeError("CRM ล่ม")

    world["loga"].add_points = boom

    world["runner"].run(world["session"], world["job"])  # ต้องไม่ raise

    assert world["status"].get("job-1").state is JobState.FAILED


def test_notification_failure_does_not_lose_points(world):
    """ส่ง LINE ไม่ได้ ต้องไม่ทำให้แต้มที่เข้าไปแล้วกลายเป็นล้มเหลว
    (แต้มเข้าถึงลูกค้าสำคัญกว่าการแจ้งเตือน)"""
    def boom(user_id, message):
        raise RuntimeError("LINE ล่ม")

    world["notifier"].notify = boom

    world["runner"].run(world["session"], world["job"])

    assert len(world["loga"].awards) == 1, "แต้มต้องเข้าแล้ว"
    assert world["status"].get("job-1").state is JobState.SUCCEEDED


# ═══════════════════════════════════════════
# คิว → runner ต่อกันได้จริง
# ═══════════════════════════════════════════

def test_job_flows_through_queue(world):
    """จำลอง worker จริง: web โยนเข้าคิว → worker ดึงออก → ทำงาน"""
    queue = JobQueue(world["redis"])
    queue.enqueue(world["job"])

    dequeued = queue.dequeue(block_seconds=1)
    assert dequeued == world["job"]

    world["runner"].run(world["session"], dequeued)
    assert world["status"].get("job-1").state is JobState.SUCCEEDED
