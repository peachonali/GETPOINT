"""web process — สร้าง FastAPI app + ประกอบ routes + middleware (auth_guard, rate_limit, errors)
รันด้วย: uvicorn app.main:app"""
from fastapi import FastAPI
from app.routes import health_routes

app = FastAPI(title="GETPOINT API")
app.include_router(health_routes.router)

# TODO: include auth_routes, scan_routes, job_routes, point_routes, admin routes
# TODO: ใส่ middleware: logging, auth_guard, rate_limit, errors
