"""เทส app/config/settings.py

โฟกัสที่กฎ HTTPS ของ loga — เป็น security control ที่ถ้าเงียบไป credential รั่วข้าม
plaintext โดยไม่มีใครรู้ (Finding 1 จาก review Step 1)

ส่ง _env_file=None ทุกครั้ง เพื่อไม่ให้ .env ของเครื่องจริงแทรกผลเทส
init arg มี priority สูงกว่า env เสมอใน pydantic-settings จึงคุมค่าได้แน่นอน
"""
import pytest
from pydantic import ValidationError

from app.config.settings import Settings


def test_http_loga_url_is_rejected():
    """พิมพ์ตก s หรือ copy จาก doc เก่า = ต้องบูตไม่ขึ้น ไม่ใช่รั่วเงียบ"""
    with pytest.raises(ValidationError):
        Settings(loga_base_url="http://loga.app", _env_file=None)


def test_https_loga_url_is_accepted():
    settings = Settings(loga_base_url="https://loga.app", _env_file=None)
    assert settings.loga_base_url == "https://loga.app"


def test_empty_loga_url_is_allowed():
    """ค่าว่าง = ยังไม่ตั้ง ให้ไปพังตอนใช้จริงด้วย error ที่ชัดกว่า
    ไม่ใช่พังตั้งแต่โหลด config บนเครื่องที่ยังไม่ได้ตั้ง loga"""
    assert Settings(loga_base_url="", _env_file=None).loga_base_url == ""


def test_default_loga_url_is_https():
    assert Settings(_env_file=None).loga_base_url.startswith("https://")
