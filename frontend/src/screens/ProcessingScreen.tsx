// หน้ารอผล — ถามสถานะงานเป็นระยะจนกว่าจะเสร็จ
//
// ★ หน้านี้มีอยู่เพราะระบบเป็น async job (ADR 0002): ลูกค้าปิดแอปไปได้เลย
//   แต้มจะเด้งมาทาง LINE — หน้านี้ไว้ให้คนที่อยากรอดูความคืบหน้า
import { useEffect, useState } from "react";

import { readJob, type JobStatus } from "../api/job-api";

//: ถามทุก 2 วินาที — ถี่พอให้รู้สึกตอบสนอง แต่ไม่ถล่ม backend
const POLL_INTERVAL_MS = 2000;
//: เลิกถามหลัง 2 นาที — งานที่นานกว่านี้ให้รอ LINE Push แทน (ไม่ปล่อยถามค้างทั้งวัน)
const MAX_POLL_MS = 120_000;

interface Props {
  jobId: string;
  idToken: string;
  onDone: (status: JobStatus) => void;
}

export function ProcessingScreen({ jobId, idToken, onDone }: Props) {
  const [waitedTooLong, setWaitedTooLong] = useState(false);

  useEffect(() => {
    // ★ ใช้ตัวแปรของ effect รอบนี้ ไม่ใช่ useRef ที่อยู่ข้ามรอบ
    //   ถ้าใช้ ref ที่ตั้ง true ตอน cleanup แล้วไม่รีเซ็ต พอ effect รันรอบใหม่
    //   (React StrictMode ตอน dev ทำ mount→cleanup→mount) polling จะตายถาวร
    let cancelled = false;
    let timer: number | undefined;
    const startedAt = Date.now();

    async function poll() {
      try {
        const status = await readJob(jobId, idToken);
        if (cancelled) return;

        if (status.state === "succeeded" || status.state === "failed") {
          onDone(status);
          return;
        }
      } catch {
        // ถามไม่สำเร็จ (เน็ตกระตุก) — ไม่ต้องแจ้งลูกค้า แค่ลองใหม่รอบหน้า
      }

      if (cancelled) return;

      if (Date.now() - startedAt > MAX_POLL_MS) {
        setWaitedTooLong(true);
        return;
      }
      timer = window.setTimeout(poll, POLL_INTERVAL_MS);
    }

    poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [jobId, idToken, onDone]);

  return (
    <div className="screen">
      <div className="card center done">
        <div className="done__badge">🧾</div>
        <h1 className="done__title">กำลังอ่านใบเสร็จ...</h1>
        <p className="subtle">
          {waitedTooLong
            ? "ใช้เวลานานกว่าปกติ — ปิดหน้านี้ได้เลย เราจะแจ้งผลทาง LINE"
            : "ปิดแอปไปทำอย่างอื่นได้เลย เราจะแจ้งแต้มทาง LINE"}
        </p>
        {!waitedTooLong && <div style={{ marginTop: 20 }}><span className="spinner" /></div>}
      </div>
    </div>
  );
}
