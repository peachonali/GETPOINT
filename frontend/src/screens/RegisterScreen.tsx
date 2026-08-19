// หน้าสมัคร/ยืนยันเบอร์ — 3 ช่วง: กรอกเบอร์ → กรอก OTP → สำเร็จ
//
// ★ ไฟล์นี้เก็บ "ตรรกะ" ล้วน (state + เรียก api) · หน้าตาทั้งหมดอยู่ที่ styles/*.css
//   เปลี่ยนดีไซน์ทีหลัง แก้ CSS/tokens ได้โดยไม่ต้องแตะไฟล์นี้
import { useState } from "react";

import { ApiError, requestOtp, verifyOtp, type VerifyResult } from "../api/auth-api";
import { OtpInput, OTP_LENGTH } from "../components/OtpInput";

type Phase = "phone" | "otp" | "success";

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return "เชื่อมต่อไม่สำเร็จ กรุณาลองใหม่";
}

// เช็คเบาๆ ฝั่งหน้าเว็บพอให้ปุ่มกดได้/ไม่ได้ — ตัวตัดสินจริงคือ backend (normalize + validate)
const looksLikePhone = (v: string) => /^\d{9,10}$/.test(v.replace(/\D/g, ""));

interface Props {
  idToken: string;
  onVerified?: () => void;  // ยืนยันสำเร็จ → App พาไปหน้าสแกน
}

export function RegisterScreen({ idToken, onVerified }: Props) {
  const [phase, setPhase] = useState<Phase>("phone");
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<VerifyResult | null>(null);

  async function onRequestOtp() {
    setBusy(true);
    setError("");
    try {
      await requestOtp(phone, idToken);
      setOtp("");
      setPhase("otp");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function onVerify() {
    setBusy(true);
    setError("");
    try {
      setResult(await verifyOtp(phone, otp, idToken));
      setPhase("success");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="screen">
      <div className="card">
        <div className="brand">
          <span className="brand__mark">V</span>
          <div>
            <div className="brand__name">V-CLUB</div>
            <div className="brand__tag">แต้มสะสม · ของรางวัล</div>
          </div>
        </div>

        {phase === "phone" && (
          <>
            <h1 className="headline">มารับแต้มกัน! 🎉</h1>
            <p className="subtle">ยืนยันเบอร์ครั้งเดียว สะสมได้ตลอด</p>
            <div className="reward">
              <span className="reward__emoji">🏆</span>
              <span>สะสมครบแลกส่วนลด &amp; ของรางวัลเพียบ</span>
            </div>
            <div className="field">
              <label className="field__label" htmlFor="phone">เบอร์โทรศัพท์</label>
              <input
                id="phone" className="input" inputMode="tel" placeholder="08X-XXX-XXXX"
                value={phone} disabled={busy}
                onChange={(e) => setPhone(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && looksLikePhone(phone)) onRequestOtp(); }}
              />
            </div>
            {error && <div className="error" role="alert">{error}</div>}
            <button className="btn" disabled={busy || !looksLikePhone(phone)} onClick={onRequestOtp}>
              {busy ? <span className="spinner" /> : "ขอรหัส OTP"}
            </button>
            <p className="fine">เราจะส่ง SMS รหัส 6 หลักไปยังเบอร์นี้</p>
          </>
        )}

        {phase === "otp" && (
          <>
            <h1 className="headline">กรอกรหัส OTP</h1>
            <p className="subtle">ส่งรหัส 6 หลักไปที่ {phone} แล้ว</p>
            <div style={{ height: 22 }} />
            <OtpInput value={otp} onChange={setOtp} disabled={busy} />
            {error && <div className="error" role="alert">{error}</div>}
            <button className="btn" disabled={busy || otp.length < OTP_LENGTH} onClick={onVerify}>
              {busy ? <span className="spinner" /> : "ยืนยัน"}
            </button>
            <div className="row">
              <button className="linkbtn" disabled={busy} onClick={() => { setPhase("phone"); setError(""); }}>
                ← แก้เบอร์
              </button>
              <button className="linkbtn" disabled={busy} onClick={onRequestOtp}>
                ส่งรหัสใหม่
              </button>
            </div>
          </>
        )}

        {phase === "success" && (
          <div className="done">
            <div className="done__badge">🎉</div>
            <h1 className="done__title">ยืนยันสำเร็จ!</h1>
            <p className="subtle">พร้อมสะสมแต้มจากทุกใบเสร็จแล้ว</p>
            {result?.crm_customer_id && (
              <p className="fine">รหัสสมาชิก {result.crm_customer_id}</p>
            )}
            {onVerified && (
              <button className="btn" onClick={onVerified}>เริ่มสแกนใบเสร็จ</button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
