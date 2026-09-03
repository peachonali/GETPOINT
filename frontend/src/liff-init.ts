// เปิด LIFF + LINE Login → ได้ ID token ไว้ส่งให้ backend ยืนยันตัวตน
import liff from "@line/liff";

import { config, isPreviewMode } from "./config";

export interface LiffSession {
  // ★ ส่งให้ backend เป็น Bearer token — backend จะ verify แล้วดึง lineUserId เอง (ปลอดภัยกว่า)
  idToken: string;
  // lineUserId เผื่อหน้าเว็บอยากใช้แสดงผล (เช่นทักชื่อ) — ไม่ใช้เป็นตัวยืนยันตัวตน
  lineUserId: string;
}

export async function initLiff(): Promise<LiffSession> {
  // โหมดพรีวิว: ยังไม่มี LIFF ID (พัฒนาในเบราว์เซอร์ปกติ) → จำลอง session ไว้ลอง UI
  if (isPreviewMode) {
    console.warn("[liff] preview mode — ใช้ session จำลอง (ยังไม่ได้ตั้ง VITE_LIFF_ID)");
    return { idToken: "preview-token", lineUserId: "preview-user" };
  }

  await liff.init({ liffId: config.liffId });

  if (!liff.isLoggedIn()) {
    // พาไปหน้า LINE Login แล้วเด้งกลับมาที่หน้านี้ — โค้ดหลังบรรทัดนี้จะไม่ทำงานต่อ
    liff.login();
    return new Promise<LiffSession>(() => {}); // ค้างไว้ระหว่างกำลัง redirect
  }

  const idToken = liff.getIDToken();
  if (!idToken) {
    throw new Error("ไม่ได้รับ ID token จาก LINE (ตรวจ scope 'openid' ของ LIFF)");
  }

  const profile = await liff.getProfile();
  return { idToken, lineUserId: profile.userId };
}
