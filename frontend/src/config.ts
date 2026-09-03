// ค่าตั้งฝั่งหน้าเว็บ — ค่าสาธารณะเท่านั้น ห้ามมี secret (ทุกอย่างที่นี่ถูกฝังลง bundle)

export const config = {
  // LIFF ID จาก LINE Login channel > แท็บ LIFF (ใส่ผ่าน .env ตอน deploy ได้ URL แล้ว)
  liffId: import.meta.env.VITE_LIFF_ID ?? "",

  // ที่อยู่ backend — dev ปล่อยว่าง (เรียก /auth/* ผ่าน vite proxy), prod ใส่ origin จริง
  apiBase: import.meta.env.VITE_API_BASE ?? "",
};

// ยังไม่มี LIFF ID = กำลังพัฒนา/พรีวิว UI ในเบราว์เซอร์ปกติ (ไม่ได้อยู่ในแอป LINE)
// → จำลอง LINE login + จำลองคำตอบ API เพื่อให้ลองกดดู flow ได้โดยไม่ต้องมี LINE/backend จริง
export const isPreviewMode = config.liffId === "";
