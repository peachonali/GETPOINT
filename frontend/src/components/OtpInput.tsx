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
    const digit = e.target.value.replace(/\D/g, "").slice(-1); // เอาเฉพาะตัวเลขตัวสุดท้าย
    if (!digit) return;
    setDigit(index, digit);
    boxes.current[index + 1]?.focus(); // เลื่อนไปช่องถัดไป
  }

  function handleKeyDown(index: number, e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && !value[index]) {
      boxes.current[index - 1]?.focus(); // ช่องว่าง กด backspace → ถอยไปช่องก่อน
    }
  }

  function handlePaste(e: ClipboardEvent<HTMLInputElement>) {
    e.preventDefault();
    const pasted = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, OTP_LENGTH);
    if (pasted) {
      onChange(pasted);
      boxes.current[Math.min(pasted.length, OTP_LENGTH - 1)]?.focus();
    }
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
