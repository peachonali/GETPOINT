// ตัวกลางยิง backend — รวม header/แปลง error ไว้ที่เดียว ทุก api ไฟล์อื่นเรียกผ่านนี้
import { config } from "../config";

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

type Method = "GET" | "POST";

async function request(method: Method, path: string, idToken: string, body?: BodyInit | object) {
  const isForm = body instanceof FormData;
  const res = await fetch(`${config.apiBase}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${idToken}`, // backend verify token นี้กับ LINE
      // FormData ต้องปล่อยให้เบราว์เซอร์ใส่ boundary เอง ห้ามตั้ง Content-Type
      ...(body && !isForm ? { "Content-Type": "application/json" } : {}),
    },
    body: isForm ? body : body ? JSON.stringify(body) : undefined,
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    // backend ส่ง {error, retry_after_seconds} มาตาม exception handler ใน main.py
    throw new ApiError(res.status, data?.error ?? "เกิดข้อผิดพลาด กรุณาลองใหม่", data?.retry_after_seconds);
  }
  return data;
}

export const api = {
  get: (path: string, idToken: string) => request("GET", path, idToken),
  post: (path: string, idToken: string, body?: BodyInit | object) =>
    request("POST", path, idToken, body),
};

export const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
