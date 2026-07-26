"""GET /health — เช็กว่าระบบยังมีชีวิต (ให้ load balancer/monitor เรียก)"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}
