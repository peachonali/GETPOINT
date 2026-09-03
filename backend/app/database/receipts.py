"""ตาราง receipts — ประวัติใบเสร็จที่ระบบเคยรับไว้

★ ทำไมต้องมีตารางนี้ (นี่คือสิ่งที่ขาดอยู่จริงๆ):
    ก่อนหน้านี้ระบบ "ไม่เคยจำ" ว่าเคยรับใบไหนไปแล้ว → ต่อให้คำนวณลายนิ้วมือได้แม่นแค่ไหน
    ก็ไม่มีอะไรให้เอาไปเทียบ → กันใบซ้ำไม่ได้เลยโดยสิ้นเชิง
    ลูกค้าถ่ายใบเดิมส่งซ้ำ = ได้แต้มทุกครั้งที่ส่ง

★ แถวนี้คือ "แหล่งความจริง" ของการให้แต้ม 1 ครั้ง
    - เขียนแถวก่อนส่งแต้ม (status=PENDING) แล้วค่อยอัปเดตเป็น AWARDED
      → ถ้าระบบล่มกลางทาง แถวยังอยู่ ทำให้ยิงซ้ำแล้วไม่ได้แต้มซ้ำ
    - `crm_reference` = id ของแถวนี้ ไม่ใช่แฮชของเนื้อหา
      เหตุผล: loga ถือว่า reference ซ้ำ = รายการเดิม (ADR 0003 #7) เราจึงอยาก
      ให้ reference "ซ้ำเมื่อเป็นแถวเดิมเท่านั้น" ไม่ใช่ซ้ำเพราะเนื้อหาบังเอิญคล้ายกัน
      (ดู ADR 0006)

★ PDPA: ตารางนี้ไม่เก็บข้อมูลส่วนบุคคลโดยตรง แต่ผูกกับ member_id ซึ่งชี้ไปหาเบอร์
   → ห้าม log ทั้งแถวดิบๆ · มีกำหนดลบตาม retention (งาน Step 7)
"""
from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import (
    JSON, Date, DateTime, Float, ForeignKey, Index, String, Time, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base

#: สถานะของใบเสร็จ 1 ใบ — เก็บเป็น string ธรรมดา (ไม่ใช้ Enum ของ DB)
#: เพราะเพิ่มสถานะใหม่แล้วไม่ต้อง migrate ชนิดข้อมูล ซึ่งบน Postgres ทำยากกว่าที่ควร
STATUS_PENDING = "PENDING"    # บันทึกแล้ว แต่ยังไม่รู้ผลการส่งแต้ม
STATUS_AWARDED = "AWARDED"    # ส่งแต้มเข้า CRM สำเร็จ
STATUS_FAILED = "FAILED"      # ส่งไม่สำเร็จ — ยังกันซ้ำอยู่ แต่ยังไม่ได้แต้ม (จะถูกส่งซ้ำ)
STATUS_DEAD = "DEAD"          # ส่งซ้ำแล้วโดนปฏิเสธเฉพาะใบนี้เกินเกณฑ์ — ต้องให้คนดู (dead letter)
STATUS_REJECTED = "REJECTED"  # ถูกปฏิเสธ (เช่นตรวจพบว่าซ้ำ)


class ReceiptRecord(Base):
    """ใบเสร็จ 1 ใบที่ระบบรับไว้ (ไม่ใช่ 1 รูป — ถ่ายซ้ำจะไม่สร้างแถวใหม่)

    ⚠ ชื่อคลาสไม่ใช่ `Receipt` โดยตั้งใจ — ชื่อนั้นถูกใช้แล้วโดยโครงข้อมูลกลาง
      `receipt_data/receipt_schema.Receipt` ซึ่ง scan_job import คู่กัน
      ตั้งชื่อชนกันแล้วต้อง alias ทุกที่ที่ใช้ ซึ่งอ่านแล้วสับสนว่ากำลังพูดถึงตัวไหน
    """

    __tablename__ = "receipts"
    __table_args__ = (
        # ★ ลายนิ้วมือเนื้อหาซ้ำ = ใบเดิมแน่นอน → กันไว้ที่ระดับฐานข้อมูลด้วย
        #   ไม่ใช่แค่ที่โค้ด · เผื่อ worker สองตัวทำงานใบเดียวกันพร้อมกัน (race)
        #   โค้ดตรวจก่อนแล้วยังชนได้ ถ้าอีกตัวเขียนแทรกระหว่างตรวจกับเขียน
        UniqueConstraint("tenant_id", "content_fingerprint", name="uq_receipt_content"),
        # duplicate_check ค้นด้วย tenant + สมาชิก + ยอด เป็นหลัก (ดูเหตุผลในไฟล์นั้น)
        Index("ix_receipts_lookup", "tenant_id", "member_id", "total_amount"),
        # กฎ "แชร์เลขอ้างอิง" ค้นข้ามสมาชิกทั้ง tenant → ต้องมี index ที่ไม่มี member_id
        Index("ix_receipts_tenant_amount", "tenant_id", "total_amount"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    tenant_id: Mapped[str] = mapped_column(String(50), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)

    #: ลายนิ้วมือเนื้อหา (ดู receipt_identity.content_fingerprint) — ทางลัดจับใบซ้ำแบบตรงเป๊ะ
    content_fingerprint: Mapped[str] = mapped_column(String(64))
    #: ลายนิ้วมือของไฟล์รูปที่ทำให้เกิดแถวนี้ — ไว้ย้อนดูว่ามาจากรูปไหน
    image_fingerprint: Mapped[str] = mapped_column(String(64), index=True)

    #: ค่าที่อ่านได้จากใบเสร็จ (อาจว่างได้ทุกตัว ยกเว้นยอดเงิน)
    merchant: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: ★ รหัสร้านที่คงที่ — ใช้ตัดสินใจ (ชื่อร้านด้านบนใช้แค่แสดงผล)
    merchant_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    receipt_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    receipt_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    receipt_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    total_amount: Mapped[float] = mapped_column(Float)

    #: ★ เลขอ้างอิงทุกตัวที่อ่านได้ — เก็บเป็น JSON array
    #:   ไม่แยกเป็นตารางลูก เพราะ query จริงกรองด้วย tenant+ยอด ก่อนเสมอ
    #:   ซึ่งเหลือแถวไม่กี่แถว แล้วค่อยเทียบเลขในหน่วยความจำ — เร็วพอที่ปริมาณของเรา
    #:   (แยกตารางเมื่อไหร่ที่การเทียบในหน่วยความจำเริ่มช้า ไม่ใช่ก่อนหน้านั้น)
    reference_codes: Mapped[list] = mapped_column(JSON, default=list)

    status: Mapped[str] = mapped_column(String(20), default=STATUS_PENDING)
    #: reference ที่ส่งให้ CRM — ตั้งหลังรู้ id ของแถว (ดู scan_job)
    crm_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    #: แต้มที่ได้จากใบนี้ (ตามที่ CRM ตอบกลับ หรือที่เราคำนวณเอง)
    points_awarded: Mapped[int | None] = mapped_column(nullable=True)
    #: จำนวนครั้งที่ส่งแต้มแล้วโดน "ปฏิเสธเฉพาะใบนี้" — ครบเกณฑ์ → ย้ายไป DEAD
    #: (ระบบล่มทั้งระบบไม่นับ เพราะไม่ใช่ความผิดของใบนี้ — ดู send_queue.py)
    send_attempts: Mapped[int] = mapped_column(default=0, server_default="0")

    #: key ของรูปต้นฉบับใน storage — ไว้ย้อนดูหลักฐานเมื่อลูกค้าทักท้วง
    source_image_id: Mapped[str] = mapped_column(String(200))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return (
            f"Receipt(id={self.id}, tenant_id={self.tenant_id!r}, "
            f"amount={self.total_amount}, status={self.status!r})"
        )
