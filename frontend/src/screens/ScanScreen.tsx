// หน้าสแกน — ถ่ายรูป/เลือกรูปใบเสร็จแล้วส่งเข้าคิว
import { useRef, useState, type ChangeEvent } from "react";

import { ApiError, submitScan } from "../api/scan-api";

interface Props {
  idToken: string;
  onQueued: (jobId: string) => void;  // ส่งสำเร็จ → ไปหน้ารอผล
}

export function ScanScreen({ idToken, onQueued }: Props) {
  const fileInput = useRef<HTMLInputElement | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function onPick(e: ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0];
    if (!picked) return;

    setFile(picked);
    setError("");
    // แสดงรูปที่เลือกให้ลูกค้าเห็นก่อนส่ง (จะได้รู้ว่าถ่ายติดครบไหม)
    setPreview((old) => {
      if (old) URL.revokeObjectURL(old);  // คืนหน่วยความจำของรูปเก่า
      return URL.createObjectURL(picked);
    });
  }

  async function onSubmit() {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const { job_id } = await submitScan(file, idToken);
      onQueued(job_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "ส่งรูปไม่สำเร็จ กรุณาลองใหม่");
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
            <div className="brand__tag">สะสมแต้มจากใบเสร็จ</div>
          </div>
        </div>

        <h1 className="headline">ถ่ายใบเสร็จ 📸</h1>
        <p className="subtle">ถ่ายให้เห็นยอดรวมชัดเจน แล้วส่งได้เลย</p>

        {preview ? (
          <img className="preview" src={preview} alt="ใบเสร็จที่เลือก" />
        ) : (
          <button className="dropzone" onClick={() => fileInput.current?.click()}>
            <span className="dropzone__icon">🧾</span>
            <span>แตะเพื่อถ่ายรูป หรือเลือกจากคลัง</span>
          </button>
        )}

        {/* capture="environment" = เปิดกล้องหลังทันทีบนมือถือ */}
        <input
          ref={fileInput} type="file" accept="image/jpeg,image/png" capture="environment"
          hidden onChange={onPick}
        />

        {error && <div className="error" role="alert">{error}</div>}

        {file && (
          <>
            <button className="btn" disabled={busy} onClick={onSubmit}>
              {busy ? <span className="spinner" /> : "ส่งใบเสร็จ"}
            </button>
            <button className="linkbtn center-block" disabled={busy}
                    onClick={() => fileInput.current?.click()}>
              เลือกรูปใหม่
            </button>
          </>
        )}

        <p className="fine">ระบบจะอ่านยอดเงินแล้วแจ้งแต้มให้ทาง LINE</p>
      </div>
    </div>
  );
}
