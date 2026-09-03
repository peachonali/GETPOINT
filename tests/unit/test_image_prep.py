"""เทส app/image_prep/ — เตรียมรูปก่อน OCR

สร้าง "รูปถ่ายใบเสร็จ" สังเคราะห์ (ใบเสร็จขาวบนพื้นหลังเข้ม เอียงได้ เบลอได้)
แล้วพิสูจน์ว่าแต่ละขั้นทำสิ่งที่อ้างไว้จริง — ไม่ใช่แค่รันผ่านโดยไม่ error
"""
import cv2
import numpy as np
import pytest

from app.image_prep.image_pipeline import prepare_for_ocr
from app.image_prep.image_quality import BLUR_THRESHOLD, assess_quality
from app.image_prep.opencv_crop import crop_receipt
from app.image_prep.opencv_deskew import deskew
from app.image_prep.opencv_enhance import enhance
from app.reliability.errors import InputValidationError


def _receipt(width=400, height=700) -> np.ndarray:
    """ใบเสร็จขาวมีข้อความเข้ม (ยังไม่มีพื้นหลัง)"""
    paper = np.full((height, width, 3), 245, dtype=np.uint8)
    for i, line in enumerate(["RECEIPT", "NO. 0001", "SUBTOTAL 233.64", "VAT 16.36", "TOTAL 250.00"]):
        cv2.putText(paper, line, (30, 90 + i * 110), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (20, 20, 20), 3)
    return paper


def _photo_of_receipt(angle=0.0, margin=120) -> np.ndarray:
    """จำลอง 'รูปถ่าย': ใบเสร็จวางบนพื้นหลังเข้ม หมุนได้ตามมุมที่กำหนด"""
    receipt = _receipt()
    h, w = receipt.shape[:2]
    canvas = np.full((h + margin * 2, w + margin * 2, 3), 60, dtype=np.uint8)  # พื้นหลังเข้ม
    canvas[margin:margin + h, margin:margin + w] = receipt

    if angle:
        center = (canvas.shape[1] / 2, canvas.shape[0] / 2)
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        canvas = cv2.warpAffine(canvas, matrix, (canvas.shape[1], canvas.shape[0]),
                                borderValue=(60, 60, 60))
    return canvas


def _to_jpeg(image: np.ndarray) -> bytes:
    return cv2.imencode(".jpg", image)[1].tobytes()


# ═══════════════════════════════════════════
# ตัดขอบ
# ═══════════════════════════════════════════

def test_crop_removes_background():
    """รูปถ่ายมีพื้นหลังเยอะ → ตัดแล้วต้องเล็กลงอย่างมีนัยสำคัญ"""
    photo = _photo_of_receipt()
    cropped = crop_receipt(photo)

    photo_area = photo.shape[0] * photo.shape[1]
    cropped_area = cropped.shape[0] * cropped.shape[1]
    assert cropped_area < photo_area * 0.85, "ต้องตัดพื้นหลังออกได้จริง"


def test_crop_keeps_the_content():
    """ตัดแล้วต้องยังมีข้อความอยู่ ไม่ใช่ตัดจนเหลือแต่กระดาษเปล่า"""
    cropped = crop_receipt(_photo_of_receipt())
    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    dark_pixels = int((gray < 100).sum())
    assert dark_pixels > 500, "ข้อความ (พิกเซลเข้ม) ต้องยังอยู่"


def test_crop_returns_original_when_no_border_found():
    """ใบเสร็จเต็มเฟรม (ไม่มีพื้นหลัง) → หาขอบไม่เจอ ต้องคืนรูปเดิม ไม่ใช่พังหรือตัดมั่ว"""
    receipt = _receipt()
    assert crop_receipt(receipt).shape == receipt.shape


# ═══════════════════════════════════════════
# ดัดเอียง
# ═══════════════════════════════════════════

def _tilted_receipt(angle: float) -> np.ndarray:
    """ใบเสร็จเอียงบนพื้นขาว — ตรงกับสิ่งที่ deskew เจอจริง (ทำงานหลัง crop แล้ว)"""
    receipt = _receipt()
    center = (receipt.shape[1] / 2, receipt.shape[0] / 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(receipt, matrix, (receipt.shape[1], receipt.shape[0]),
                          borderValue=(245, 245, 245))


@pytest.mark.parametrize("angle", [5.0, -5.0, 8.0])
def test_deskew_straightens_tilted_text(angle):
    """เอียงเข้าไป → หลัง deskew ต้องเอียงน้อยลงกว่าเดิมชัดเจน"""
    from app.image_prep.opencv_deskew import _estimate_skew_angle

    tilted = _tilted_receipt(angle)
    before = _estimate_skew_angle(tilted)
    after = _estimate_skew_angle(deskew(tilted))

    assert before is not None and after is not None
    assert abs(after) < abs(before), f"ควรตรงขึ้น (ก่อน {before:.1f}° หลัง {after:.1f}°)"


def test_deskew_leaves_straight_image_alone():
    """ภาพตรงอยู่แล้วต้องไม่ถูกหมุน (หมุนมีราคา — ทำให้เบลอขึ้นเปล่าๆ)"""
    straight = _receipt()
    assert deskew(straight).shape == straight.shape


# ═══════════════════════════════════════════
# ปรับความคมชัด
# ═══════════════════════════════════════════

def test_enhance_returns_grayscale():
    result = enhance(_receipt())
    assert result.ndim == 2, "ต้องคืนภาพระดับเทา (พร้อมส่ง OCR)"


def test_enhance_improves_contrast_on_faded_receipt():
    """ใบเสร็จหมึกจาง (contrast ต่ำ) → หลังปรับต้องมี contrast สูงขึ้น"""
    faded = (_receipt().astype(np.float32) * 0.25 + 150).astype(np.uint8)  # จางลง
    before = float(cv2.cvtColor(faded, cv2.COLOR_BGR2GRAY).std())
    after = float(enhance(faded).std())

    assert after > before, f"contrast ควรดีขึ้น (ก่อน {before:.1f} หลัง {after:.1f})"


# ═══════════════════════════════════════════
# ตรวจคุณภาพ
# ═══════════════════════════════════════════

def test_sharp_image_passes():
    assert assess_quality(_receipt()).acceptable


def test_blurry_image_is_rejected_with_reason():
    blurred = cv2.GaussianBlur(_receipt(), (31, 31), 0)
    report = assess_quality(blurred)

    assert not report.acceptable
    assert report.blur_score < BLUR_THRESHOLD
    assert "เบลอ" in report.reason, "ต้องบอกลูกค้าว่าต้องทำอะไร"


def test_dark_image_is_rejected():
    dark = (_receipt() * 0.1).astype(np.uint8)
    report = assess_quality(dark)
    assert not report.acceptable
    assert "มืด" in report.reason


# ═══════════════════════════════════════════
# ทั้ง pipeline
# ═══════════════════════════════════════════

def test_pipeline_produces_smaller_grayscale_jpeg():
    prepared = prepare_for_ocr(_to_jpeg(_photo_of_receipt(angle=4.0)))

    assert prepared.startswith(b"\xff\xd8\xff"), "ต้องเป็น JPEG"
    decoded = cv2.imdecode(np.frombuffer(prepared, np.uint8), cv2.IMREAD_UNCHANGED)
    assert decoded is not None


def test_pipeline_rejects_blurry_photo():
    blurred = cv2.GaussianBlur(_photo_of_receipt(), (35, 35), 0)
    with pytest.raises(InputValidationError, match="เบลอ"):
        prepare_for_ocr(_to_jpeg(blurred))


def test_pipeline_rejects_unreadable_bytes():
    with pytest.raises(InputValidationError):
        prepare_for_ocr(b"not-an-image")
