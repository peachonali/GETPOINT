// ช่องกรอกรหัส OTP — 6 ช่อง เลื่อนช่องอัตโนมัติ + วางทั้งรหัสได้
import { useRef, type ChangeEvent, type ClipboardEvent, type KeyboardEvent } from "react";

const OTP_LENGTH = 6;

interface Props {
  value: string;                    // รหัสปัจจุบัน (สตริงตัวเลข ยาวไม่เกิน 6)
  onChange: (next: string) => void; // ส่งรหัสใหม่กลับให้หน้าจอแม่
  disabled?: boolean;
}

export function OtpInput({ value, onChange, disabled }: Props) {
  const boxes = useRef<Array<HTMLInputElement | null>>([]);

  function setDigit(index: number, digit: string) {
    const chars = value.split("");
    chars[index] = digit;
    onChange(chars.join("").slice(0, OTP_LENGTH));
  }

  function handleChange(index: number, e: ChangeEvent<HTMLInputElement>) {
    const digits = e.target.value.replace(/\D/g, "");
    if (!digits) return;

    // ★ รับได้ทั้งพิมพ์ทีละตัว และ "มาทีเดียวหลายตัว"
    //   เคสหลังเกิดจริงบน Android: SMS autofill ยัดรหัสทั้ง 6 หลักลงช่องเดียว
    //   ถ้าเก็บแค่ตัวเดียวจะทิ้งอีก 5 ตัวทิ้ง แล้วลูกค้าต้องพิมพ์เองใหม่
    if (digits.length > 1) {
      fill(digits, index);
      return;
    }

    setDigit(index, digits);
    boxes.current[index + 1]?.focus(); // เลื่อนไปช่องถัดไป
  }

  function fill(digits: string, from: number) {
    const chars = value.split("");
    for (let i = 0; i < digits.length && from + i < OTP_LENGTH; i += 1) {
      chars[from + i] = digits[i];
    }
    const next = chars.join("").slice(0, OTP_LENGTH);
    onChange(next);
    boxes.current[Math.min(from + digits.length, OTP_LENGTH - 1)]?.focus();
  }

  function handleKeyDown(index: number, e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && !value[index]) {
      boxes.current[index - 1]?.focus(); // ช่องว่าง กด backspace → ถอยไปช่องก่อน
    }
  }

  function handlePaste(e: ClipboardEvent<HTMLInputElement>) {
    e.preventDefault();
    const pasted = e.clipboardData.getData("text").replace(/\D/g, "");
    if (pasted) fill(pasted, 0);  // วางทั้งรหัส → เริ่มเติมจากช่องแรกเสมอ
  }

  return (
    <div className="otp" role="group" aria-label="รหัส OTP 6 หลัก">
      {Array.from({ length: OTP_LENGTH }).map((_, i) => (
        <input
          key={i}
          ref={(el) => { boxes.current[i] = el; }}
          className="otp__box"
          inputMode="numeric"
          autoComplete={i === 0 ? "one-time-code" : "off"}
          maxLength={1}
          value={value[i] ?? ""}
          disabled={disabled}
          aria-label={`หลักที่ ${i + 1}`}
          onChange={(e) => handleChange(i, e)}
          onKeyDown={(e) => handleKeyDown(i, e)}
          onPaste={handlePaste}
        />
      ))}
    </div>
  );
}

export { OTP_LENGTH };
