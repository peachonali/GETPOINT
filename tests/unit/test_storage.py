"""เทส app/storage/ — LocalStorage + ImageStore

ใช้ tmp_path (โฟลเดอร์ชั่วคราวจริงของ pytest) ไม่ mock filesystem
เพราะสิ่งที่ต้องพิสูจน์คือพฤติกรรมกับดิสก์จริง โดยเฉพาะการกัน path traversal
"""
import pytest

from app.storage.image_store import ImageStore
from app.storage.local_storage import LocalStorage
from app.storage.storage_interface import StoragePort

IMAGE = b"\xff\xd8\xff-pretend-this-is-a-jpeg"


@pytest.fixture
def storage(tmp_path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage_data")


# ═══════════════════════════════════════════
# LocalStorage
# ═══════════════════════════════════════════

def test_is_a_storage_port(storage):
    assert isinstance(storage, StoragePort)


def test_save_then_load(storage):
    storage.save("receipts/v-club/abc.jpg", IMAGE)
    assert storage.load("receipts/v-club/abc.jpg") == IMAGE


def test_creates_nested_folders(storage):
    """key มี / ซ้อนหลายชั้น ต้องสร้างโฟลเดอร์ให้เอง ไม่ใช่พัง"""
    storage.save("a/b/c/deep.jpg", IMAGE)
    assert storage.exists("a/b/c/deep.jpg")


def test_delete_existing_file(storage):
    """ลบไฟล์ที่มีอยู่ → True แล้วไฟล์หายจริง (ใช้ตอน retention)"""
    storage.save("receipts/v-club/x.jpg", IMAGE)
    assert storage.delete("receipts/v-club/x.jpg") is True
    assert not storage.exists("receipts/v-club/x.jpg")


def test_delete_missing_file_is_not_error(storage):
    """★ ลบของที่ไม่มี → False ไม่ใช่ error (retention รันซ้ำบนของที่ลบไปแล้วได้)"""
    assert storage.delete("receipts/v-club/nope.jpg") is False


def test_delete_guards_path_traversal(storage):
    """ลบก็ต้องกัน path traversal เหมือน save/load"""
    with pytest.raises(ValueError):
        storage.delete("../../etc/passwd")


def test_missing_file_raises(storage):
    with pytest.raises(FileNotFoundError):
        storage.load("ไม่มีไฟล์นี้.jpg")


def test_overwrite_replaces_content(storage):
    storage.save("x.jpg", IMAGE)
    storage.save("x.jpg", b"new-content")
    assert storage.load("x.jpg") == b"new-content"


# ═══════════════════════════════════════════
# ★ ความปลอดภัย — path traversal
# ═══════════════════════════════════════════

@pytest.mark.parametrize("evil_key", [
    "../escaped.jpg",
    "../../etc/passwd",
    "receipts/../../outside.jpg",
])
def test_rejects_path_traversal(storage, evil_key):
    """key ที่มี ../ จะพาไฟล์ไปโผล่นอกโฟลเดอร์ที่ตั้งใจ (เขียนทับไฟล์ระบบได้)"""
    with pytest.raises(ValueError):
        storage.save(evil_key, IMAGE)


def test_traversal_blocked_on_read_too(storage):
    with pytest.raises(ValueError):
        storage.load("../../secret.txt")


# ═══════════════════════════════════════════
# ImageStore — ตั้งชื่อ key เป็นระบบ
# ═══════════════════════════════════════════

def test_put_then_get_roundtrip(storage):
    store = ImageStore(storage)
    store.put("v-club", "receipt-1", IMAGE)
    assert store.get("v-club", "receipt-1") == IMAGE


def test_tenants_are_isolated(storage):
    """คนละแบรนด์ต้องไม่เห็นรูปกัน — แยกโฟลเดอร์ตั้งแต่วันแรก"""
    store = ImageStore(storage)
    store.put("v-club", "same-id", b"vclub-image")
    store.put("other-brand", "same-id", b"other-image")

    assert store.get("v-club", "same-id") == b"vclub-image"
    assert store.get("other-brand", "same-id") == b"other-image"


def test_key_includes_tenant_and_receipt(storage):
    key = ImageStore(storage).put("v-club", "r-99", IMAGE)
    assert "v-club" in key and "r-99" in key
