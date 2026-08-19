// หน้าแสดงผล — สำเร็จโชว์แต้ม / ล้มเหลวบอกว่าต้องทำอะไรต่อ
import type { JobStatus } from "../api/job-api";

interface Props {
  status: JobStatus;
  onScanAgain: () => void;
}

export function ResultScreen({ status, onScanAgain }: Props) {
  const succeeded = status.state === "succeeded";

  return (
    <div className="screen">
      <div className="card center done">
        <div className="done__badge">{succeeded ? "🎉" : "😕"}</div>

        <h1 className="done__title">
          {succeeded ? "บันทึกใบเสร็จสำเร็จ!" : "บันทึกไม่สำเร็จ"}
        </h1>

        {succeeded ? (
          <>
            {status.points_balance !== null && (
              <p className="balance">
                {status.points_balance.toLocaleString("th-TH")}
                <span className="balance__unit"> แต้ม</span>
              </p>
            )}
            <p className="subtle">แต้มสะสมล่าสุดของคุณ</p>
          </>
        ) : (
          // ข้อความจาก backend บอกอยู่แล้วว่าต้องทำอะไร (เช่น "ถ่ายให้ชัดขึ้น")
          <div className="error" role="alert">
            {status.message ?? "เกิดข้อผิดพลาด กรุณาลองใหม่อีกครั้ง"}
          </div>
        )}

        <button className="btn" onClick={onScanAgain}>
          {succeeded ? "สแกนใบถัดไป" : "ลองใหม่อีกครั้ง"}
        </button>
      </div>
    </div>
  );
}
