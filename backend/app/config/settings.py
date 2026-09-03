"""อ่าน config/secret จาก env — ที่เดียวของทั้งระบบ ไฟล์อื่นเรียกผ่านนี้ ห้าม hardcode"""
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    env: str = "dev"
    database_url: str = ""
    redis_url: str = ""
    # loga
    loga_base_url: str = "https://loga.app"
    loga_user: str = ""         # ปกติคืออีเมลที่ใช้สมัคร Loga Merchant
    loga_password: str = ""     # secret — ใส่ "รหัสผ่านตัวจริง" ไม่ใช่ MD5
    #                             (loga บังคับส่งเป็น MD5 แต่เราแฮชให้ตอนยิง ดู loga_token.py)
    loga_card_id: str = ""      # เลขที่บัตรสมาชิก — required เกือบทุก endpoint
    #                             ดูได้จากเว็บ Loga Merchant แถบ Manage/จัดการ ส่วน Card Info
    loga_device_id: str = ""    # loga เรียก uuid — ★ ตั้งแล้วห้ามเปลี่ยน ต้องใช้คู่กับ token ตลอดไป
    loga_formula_id: str = ""   # สูตรคิดแต้ม (ดูจาก get_card_detail) — Step 5 จะย้ายไปตั้งต่อร้าน
    loga_timeout_seconds: float = 10.0  # ทุก external call ต้องมี timeout เสมอ
    # line
    line_login_channel_id: str = ""   # LINE Login channel — verify LIFF ID token (ดู docs/line_setup.md)
    line_channel_token: str = ""       # Messaging API — push แจ้งแต้ม (Step 3)
    # หนึ่ง channel = หนึ่งแบรนด์ในเฟสนี้ · วันมีลูกค้ารายที่ 2 ค่อย map channel -> tenant
    default_tenant_id: str = "v-club"
    # ที่เก็บไฟล์ (รูปใบเสร็จ) — วันหน้าเปลี่ยนเป็น S3 ค่อยเพิ่ม config ของ S3
    storage_dir: str = "storage_data"
    # ocr: "paddle" = ของจริง · "fake" = คืนค่าคงที่ (ใช้เทส/ตอน dev ที่ไม่อยากโหลดโมเดล)
    ocr_engine: str = "paddle"
    ocr_lang: str = "th"
    # sms / gemini
    sms_api_key: str = ""
    gemini_api_key: str = ""
    # โทเคนเข้าหน้า admin (ดูคิวค้าง/สั่งส่งซ้ำ/export) — ตั้งใน env เท่านั้น
    # ว่าง = ปิดหน้า admin ทั้งหมด (ปลอดภัยโดยปริยาย — ไม่เผลอเปิดให้ใครเข้าโดยไม่ตั้งใจ)
    admin_token: str = ""

    @field_validator("loga_base_url")
    @classmethod
    def _loga_must_be_https(cls, value: str) -> str:
        """บังคับ HTTPS จริง ไม่ใช่แค่หวังว่าคนตั้ง env ถูก

        loga ส่ง token/password/เบอร์ลูกค้า "ผ่าน query string" ทั้งหมด → ถ้าไม่ใช่ https
        เท่ากับส่ง credential ข้าม plaintext ให้ใครดักก็ได้ · CONTEXT ข้อ 3 สั่ง "HTTPS เสมอ"
        ถ้าตั้ง http มา ระบบต้อง "ไม่บูตขึ้น" ตั้งแต่ต้น ดีกว่ายอมขึ้นแล้วรั่วเงียบๆ

        ปล่อยค่าว่างผ่าน (= ยังไม่ตั้ง) เพื่อให้ fail ตอนใช้จริงด้วย error ที่ชี้ชัดกว่า
        และไม่ให้เครื่อง dev/CI ที่ไม่ได้ตั้ง loga พัง import ตั้งแต่โหลด config
        """
        if value and not value.startswith("https://"):
            raise ValueError("LOGA_BASE_URL ต้องเป็น https:// (loga ส่ง credential ใน query string)")
        return value


settings = Settings()
