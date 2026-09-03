/// <reference types="vite/client" />

// ค่า env ฝั่งหน้าเว็บ (ขึ้นต้น VITE_ ถึงจะถูกฝังตอน build) — ค่าสาธารณะเท่านั้น
interface ImportMetaEnv {
  readonly VITE_LIFF_ID?: string;   // LIFF ID จาก LINE Login channel (ใส่ตอน deploy)
  readonly VITE_API_BASE?: string;  // origin ของ backend ตอน prod
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
