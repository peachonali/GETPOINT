"""ยามหลังบ้าน — กั้นหน้า admin ไม่ให้ลูกค้าทั่วไปเข้า

★ คนละชั้นกับ auth_guard (ยามลูกค้า) โดยสิ้นเชิง:
    auth_guard  → "คุณคือลูกค้า LINE คนไหน" (ยืนยันตัวตนกับ LINE)
    admin_guard → "คุณเป็นทีมดูแลระบบไหม" (โทเคนลับที่ตั้งใน env)
  แยกไฟล์เพราะถ้าปนกัน วันหนึ่งจะเผลอให้ลูกค้าเข้าหน้า admin ได้ด้วย token ลูกค้า

★ ยังไม่ทำ RBAC เต็มรูป (CONTEXT ข้อ 3 จงใจตัดออก) — วันนี้มีบทบาทเดียว: "แอดมิน"
  ใช้โทเคนลับตัวเดียว (ADMIN_TOKEN) ผ่าน header Authorization: Bearer <token>
  วันที่ต้องแยกสิทธิ์หลายระดับค่อยเพิ่ม — เขียน RBAC วันนี้ = เดาอนาคต

★ เทียบโทเคนแบบ constant-time (secrets.compare_digest) — กัน timing attack
  เดาโทเคนทีละตัวอักษรจากเวลาตอบ · ราคาถูกมากที่จะทำให้ถูก จึงทำเลย

⚠ ADMIN_TOKEN ว่าง = ปิดหน้า admin ทั้งหมด (ตอบ 403 ทุกคำขอ)
  ปลอดภัยโดยปริยาย — เครื่องที่ลืมตั้ง token จะไม่เผลอเปิดหน้า admin ให้ใครเข้า
"""
from __future__ import annotations

import secrets

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.reliability.errors import AuthenticationError
from app.routes.dependencies import get_admin_token

#: auto_error=False — จัดการเคส "ไม่มี header" เองด้วย error ของเรา (จะได้เป็น HTTP เดียวกับที่อื่น)
_bearer = HTTPBearer(auto_error=False)


def require_admin(
    configured: str = Depends(get_admin_token),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """ผ่านได้เฉพาะคำขอที่แนบโทเคนแอดมินถูกต้อง · ไม่ผ่าน → AuthenticationError (→ 401)"""
    # ★ ปิดโดยปริยาย: ไม่ได้ตั้งโทเคน = ไม่มีทางเข้าได้
    if not configured:
        raise AuthenticationError("หน้าจัดการยังไม่ถูกเปิดใช้งาน")

    supplied = credentials.credentials if credentials else ""
    if not secrets.compare_digest(supplied, configured):
        raise AuthenticationError("โทเคนผู้ดูแลไม่ถูกต้อง")
