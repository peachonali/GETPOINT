"""★ ทางออก Excel — ดึงใบเสร็จที่ "ยังไม่ได้แต้ม" ออกมาเป็นไฟล์ให้คนอัปโหลดเข้า loga เอง

★ ทำไมต้องมี (CONTEXT ข้อ 2):
  ถ้า loga ล่มยาว (หรือเรายังต่อ loga จริงไม่ได้) แต้มของลูกค้าจะค้างเป็น FAILED
  ระบบต้องมี "ทางออกที่ไม่พึ่ง API" เพื่อไม่ให้ลูกค้าเสียแต้มที่ควรได้
  loga มีหน้า Import อยู่แล้ว → เราแค่ export ให้ตรงรูปแบบที่หน้านั้นรับ

★ นี่คือ "ตาข่ายรับสุดท้าย" ที่ทำให้ระบบปลอดภัยพอจะเปิดใช้ได้ แม้ก่อนพิสูจน์ loga จริง
  ล่มหนักแค่ไหน แต้มก็ไม่หาย — มีไฟล์ให้คนกู้คืนด้วยมือเสมอ

⚠ คอลัมน์ในไฟล์ต้องตรงกับที่หน้า Import ของ loga คาดหวัง
  ตอนนี้เดาจากพารามิเตอร์ของ add_customer_point (cuid/cost/formula_id/reference)
  → ยืนยันกับหน้า Import จริงแล้วปรับ (หนี้ที่รู้ตัว — ดู STATE)
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.members import Member
from app.database.receipts import STATUS_DEAD, STATUS_FAILED, STATUS_PENDING, ReceiptRecord

#: สถานะที่ถือว่า "ยังไม่ได้แต้ม" — ต้องเอาออกมากู้คืนด้วยมือ
#: รวม DEAD ด้วย เพราะ dead letter คือใบที่ระบบยอมแพ้แล้ว → ยิ่งต้องกู้ด้วยมือ
_UNSENT_STATUSES = (STATUS_FAILED, STATUS_PENDING, STATUS_DEAD)

#: หัวตารางในไฟล์ Excel — ภาษาอังกฤษเพื่อให้ตรงกับหน้า Import ของ loga
#: (ปรับให้ตรงกับของจริงเมื่อยืนยันแล้ว)
_HEADERS = ("reference", "customer_id", "cost", "formula_id", "merchant", "receipt_date", "status")


@dataclass(frozen=True)
class ExportResult:
    """ผลการ export — คืนจำนวนแถวด้วย เพื่อให้ผู้เรียก log/แจ้งได้ว่าเอาออกมากี่ใบ"""

    content: bytes
    row_count: int


def export_unsent(session: Session, tenant_id: str, *, formula_id: str) -> ExportResult:
    """ดึงใบเสร็จที่ยังไม่ได้แต้มของแบรนด์นี้ออกมาเป็นไฟล์ .xlsx (ในหน่วยความจำ)

    formula_id รับเข้ามา (ไม่ไปดึง settings เอง) เพราะไฟล์นี้เป็นชั้นโดเมน ไม่ควรรู้จัก
    config โดยตรง · ผู้เรียกที่ composition root เป็นคนส่งค่าให้

    คืนเป็น bytes ไม่เขียนลงดิสก์เอง — ให้ผู้เรียก (route/CLI) ตัดสินว่าจะเซฟที่ไหน
    หรือส่งให้ดาวน์โหลด · ทดสอบง่ายกว่าและไม่ผูกกับ filesystem
    """
    rows = _fetch_unsent(session, tenant_id)
    workbook = _build_workbook(rows, formula_id=formula_id)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return ExportResult(content=buffer.getvalue(), row_count=len(rows))


def _fetch_unsent(session: Session, tenant_id: str) -> list[tuple[ReceiptRecord, str | None]]:
    """ใบเสร็จที่ยังไม่ได้แต้ม + รหัสสมาชิกฝั่ง CRM (join จาก member)

    ★ ต้องมี crm_customer_id ในไฟล์ ไม่งั้นคนอัปโหลดเข้า loga ไม่ได้ = กู้คืนไม่ได้จริง
      (ตาราง receipts เก็บแค่ member_id ต้อง join member มาเอา cuid)
    """
    statement = (
        select(ReceiptRecord, Member.crm_customer_id)
        .join(Member, Member.id == ReceiptRecord.member_id)
        .where(ReceiptRecord.tenant_id == tenant_id)
        .where(ReceiptRecord.status.in_(_UNSENT_STATUSES))
        .order_by(ReceiptRecord.created_at)  # เก่าสุดก่อน — คนกู้จะได้ทำตามลำดับที่เกิด
    )
    return list(session.execute(statement).all())


def _build_workbook(
    rows: list[tuple[ReceiptRecord, str | None]], *, formula_id: str
) -> Workbook:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "unsent_points"
    sheet.append(_HEADERS)

    for record, customer_id in rows:
        sheet.append((
            record.crm_reference or "",
            customer_id or "",   # ว่างได้เฉพาะสมาชิกที่ยังผูก CRM ไม่สำเร็จ (คนกู้ต้องเช็ค)
            f"{record.total_amount:.2f}",
            formula_id,          # สูตรเดียวทั้งระบบวันนี้ · Step 5 จะอ่านต่อร้าน
            record.merchant or "",
            _format_date(record.receipt_date),
            record.status,
        ))
    return workbook


def _format_date(value: date | None) -> str:
    return value.isoformat() if value else ""
