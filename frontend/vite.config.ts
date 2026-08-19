import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// ตอน dev: เรียก /auth/* จากหน้าเว็บแล้วให้ vite ส่งต่อไป backend ที่ localhost:8000
// (เลี่ยงปัญหา CORS ระหว่างพัฒนา) · ตอน prod ใช้ VITE_API_BASE ชี้ origin จริงแทน
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/auth": "http://localhost:8000",
    },
  },
});
