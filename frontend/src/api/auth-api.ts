// ยิง backend เรื่องสมัคร/OTP — ต่อกับ /auth/* ที่เขียนไว้ฝั่ง FastAPI
import { config, isPreviewMode } from "../config";

// error ที่มี status + retryAfter ให้หน้าจอเอาไปแสดงข้อความ/นับถอยหลังได้
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public retryAfterSeconds?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface VerifyResult {
  status: "verified";
  crm_customer_id: string | null;
}

async function postJson(path: string, idToken: string, body: unknown): Promise<any> {
  const res = await fetch(`${config.apiBase}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${idToken}`, // backend verify token นี้กับ LINE
    },
    body: JSON.stringify(body),
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    // backend ส่ง {error, retry_after_seconds} มาตาม exception handler ใน main.py
    throw new ApiError(res.status, data?.error ?? "เกิดข้อผิดพลาด กรุณาลองใหม่", data?.retry_after_seconds);
  }
  return data;
}

// ── โหมดพรีวิว: จำลองคำตอบ backend เพื่อลอง flow ในเบราว์เซอร์ปกติ (OTP ที่ถูกคือ 123456) ──
const PREVIEW_OTP = "123456";
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function requestOtp(phone: string, idToken: string): Promise<void> {
  if (isPreviewMode) {
    await sleep(600);
    console.info(`[preview] OTP จำลองคือ ${PREVIEW_OTP}`);
    return;
  }
  await postJson("/auth/request-otp", idToken, { phone });
}

export async function verifyOtp(phone: string, otp: string, idToken: string): Promise<VerifyResult> {
  if (isPreviewMode) {
    await sleep(600);
    if (otp !== PREVIEW_OTP) throw new ApiError(400, "รหัส OTP ไม่ถูกต้อง (พรีวิว: ใช้ 123456)");
    return { status: "verified", crm_customer_id: "P-preview" };
  }
  return postJson("/auth/verify", idToken, { phone, otp });
}
