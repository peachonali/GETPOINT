// ยิง backend เรื่องสมัคร/OTP — ต่อกับ /auth/* ที่เขียนไว้ฝั่ง FastAPI
import { isPreviewMode } from "../config";
import { ApiError, api, sleep } from "./client";

export interface VerifyResult {
  status: "verified";
  crm_customer_id: string | null;
}

export interface MeResult {
  verified: boolean;
}

// ── โหมดพรีวิว: จำลองคำตอบ backend เพื่อลอง flow ในเบราว์เซอร์ปกติ (OTP ที่ถูกคือ 123456) ──
const PREVIEW_OTP = "123456";
let previewVerified = false;

export async function readMe(idToken: string): Promise<MeResult> {
  if (isPreviewMode) {
    await sleep(300);
    return { verified: previewVerified };
  }
  return api.get("/auth/me", idToken) as Promise<MeResult>;
}

export async function requestOtp(phone: string, idToken: string): Promise<void> {
  if (isPreviewMode) {
    await sleep(600);
    console.info(`[preview] OTP จำลองคือ ${PREVIEW_OTP}`);
    return;
  }
  await api.post("/auth/request-otp", idToken, { phone });
}

export async function verifyOtp(phone: string, otp: string, idToken: string): Promise<VerifyResult> {
  if (isPreviewMode) {
    await sleep(600);
    if (otp !== PREVIEW_OTP) throw new ApiError(400, "รหัส OTP ไม่ถูกต้อง (พรีวิว: ใช้ 123456)");
    previewVerified = true;
    return { status: "verified", crm_customer_id: "P-preview" };
  }
  return api.post("/auth/verify", idToken, { phone, otp }) as Promise<VerifyResult>;
}

export { ApiError };
