"""เทส app/storage/ocr_text_store.py — เก็บ/อ่านข้อความ OCR ดิบ"""
import pytest

from app.storage.local_storage import LocalStorage
from app.storage.ocr_text_store import OcrTextStore

TENANT = "v-club"


@pytest.fixture
def store(tmp_path) -> OcrTextStore:
    return OcrTextStore(LocalStorage(tmp_path / "storage"))


def test_put_then_get_roundtrip(store):
    lines = ["KFC 149.00", "Total 149.00", "ขอบคุณครับ"]
    store.put(TENANT, "rcp-1", lines)
    assert store.get(TENANT, "rcp-1") == lines


def test_thai_survives(store):
    """ภาษาไทยต้องเก็บ/อ่านกลับได้ครบ (UTF-8)"""
    lines = ["ร้านค้าทดสอบ", "รวมทั้งสิ้น 250 บาท"]
    store.put(TENANT, "rcp-2", lines)
    assert store.get(TENANT, "rcp-2") == lines


def test_key_is_txt_next_to_image(store):
    """key เป็น .txt ใต้โฟลเดอร์ tenant เดียวกับรูป — retention ลบพร้อมกันได้"""
    key = store.put(TENANT, "rcp-3", ["x"])
    assert key == "receipts/v-club/rcp-3.txt"


def test_empty_lines(store):
    store.put(TENANT, "rcp-4", [])
    assert store.get(TENANT, "rcp-4") == []
