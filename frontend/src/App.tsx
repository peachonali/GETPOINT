// ตัวประกอบหน้าเว็บ — เปิด LIFF (ได้ตัวตน) แล้วพาไปหน้าที่ถูกตามสถานะของลูกค้า
//
//   ยังไม่ยืนยันเบอร์ → RegisterScreen
//   ยืนยันแล้ว        → ScanScreen → ProcessingScreen → ResultScreen → กลับไป ScanScreen
import { useCallback, useEffect, useState } from "react";

import { readMe } from "./api/auth-api";
import type { JobStatus } from "./api/job-api";
import { initLiff, type LiffSession } from "./liff-init";
import { ProcessingScreen } from "./screens/ProcessingScreen";
import { RegisterScreen } from "./screens/RegisterScreen";
import { ResultScreen } from "./screens/ResultScreen";
import { ScanScreen } from "./screens/ScanScreen";

type Boot =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; session: LiffSession; verified: boolean };

type Flow =
  | { name: "scan" }
  | { name: "processing"; jobId: string }
  | { name: "result"; status: JobStatus };

export function App() {
  const [boot, setBoot] = useState<Boot>({ status: "loading" });
  const [flow, setFlow] = useState<Flow>({ name: "scan" });

  useEffect(() => {
    initLiff()
      .then(async (session) => {
        // ถาม backend ว่าคนนี้ยืนยันเบอร์ไปแล้วหรือยัง — คนเก่าจะได้ไม่เจอหน้าสมัครซ้ำ
        const me = await readMe(session.idToken).catch(() => ({ verified: false }));
        setBoot({ status: "ready", session, verified: me.verified });
      })
      .catch((err) =>
        setBoot({ status: "error", message: err?.message ?? "เปิด LINE ไม่สำเร็จ" }),
      );
  }, []);

  const onVerified = useCallback(() => {
    setBoot((prev) => (prev.status === "ready" ? { ...prev, verified: true } : prev));
    setFlow({ name: "scan" });
  }, []);

  // ★ ต้อง memo — ProcessingScreen ใช้ตัวนี้เป็น dependency ของ effect ที่ตั้ง polling
  //   ถ้าสร้างใหม่ทุก render effect จะถูกล้างแล้วตั้งใหม่ไม่จบ (polling ไม่คืบหน้า)
  const onJobDone = useCallback((status: JobStatus) => {
    setFlow({ name: "result", status });
  }, []);

  const onQueued = useCallback((jobId: string) => {
    setFlow({ name: "processing", jobId });
  }, []);

  const onScanAgain = useCallback(() => setFlow({ name: "scan" }), []);

  if (boot.status === "loading") {
    return <div className="screen center-screen"><span className="spinner" /></div>;
  }

  if (boot.status === "error") {
    return (
      <div className="screen center-screen">
        <div className="card center">
          <p className="subtle">เปิดหน้านี้ผ่านแอป LINE ไม่สำเร็จ</p>
          <div className="error" role="alert">{boot.message}</div>
        </div>
      </div>
    );
  }

  const { session, verified } = boot;

  if (!verified) {
    return <RegisterScreen idToken={session.idToken} onVerified={onVerified} />;
  }

  if (flow.name === "processing") {
    return (
      <ProcessingScreen jobId={flow.jobId} idToken={session.idToken} onDone={onJobDone} />
    );
  }

  if (flow.name === "result") {
    return <ResultScreen status={flow.status} onScanAgain={onScanAgain} />;
  }

  return (
    <ScanScreen idToken={session.idToken} onQueued={onQueued} />
  );
}
