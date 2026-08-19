"""★ เทสทั้งเส้น: รูปใบเสร็จ → OCR → แยกค่า → แต้มเข้า CRM → แจ้งลูกค้า

นี่คือเป้าหมายของ Step 3 — พิสูจน์ว่าสถาปัตยกรรมทั้งหมดต่อกันได้จริง
ใช้ของปลอมเฉพาะ "ปลายทางที่อยู่นอกระบบเรา" (OCR/CRM/LINE/Redis)
ส่วนตรรกะทั้งหมดตรงกลางเป็นของจริง — เทสนี้จึงพังจริงถ้า pipeline พัง
"""
import fakeredis
import pytest

from app.database.members import Member
from app.external.fake_loga import FakeLoga
from app.external.fake_notifier import FakeNotifier
from app.jobs.job_queue import JobQueue, ScanJob
from app.jobs.job_status import JobState, JobStatusStore
from app.jobs.scan_job import ScanJobRunner
from app.ocr.fake_ocr import FakeOcr
from app.points.crm_formula_strategy import CrmFormulaStrategy
from app.points.point_service import PointService
from app.storage.image_store import ImageStore
from app.storage.local_storage import LocalStorage

TENANT = "v-club"
LINE_USER = "U-line-1"
PHONE = "0812345678"
RECEIPT_ID = "rcp-001"
IMAGE = b"\xff\xd8\xff-fake-receipt-photo"


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

    runner = ScanJobRunner(
        image_store=images,
        ocr=ocr,
        points=PointService(CrmFormulaStrategy(loga, formula_id="7")),
        notifier=notifier,
        status_store=status_store,
    )
    job = ScanJob(
        job_id="job-1", tenant_id=TENANT, member_id=member.id,
        receipt_id=RECEIPT_ID, image_key=image_key,
    )

    return {
        "runner": runner, "job": job, "session": db_session, "redis": redis,
        "loga": loga, "notifier": notifier, "ocr": ocr, "status": status_store,
        "member": member,
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
    ★ นี่คือการพิสูจน์ว่า idempotency ผ่าน reference ทำงานจริงทั้งสาย"""
    world["runner"].run(world["session"], world["job"])
    balance_after_first = world["loga"].find_customer(PHONE).points_balance

    world["runner"].run(world["session"], world["job"])  # รอบสอง

    assert world["loga"].find_customer(PHONE).points_balance == balance_after_first
    assert len(world["loga"].awards) == 1, "CRM ต้องบันทึกรายการเดียว"


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
