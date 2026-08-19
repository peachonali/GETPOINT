// ตัวประกอบหน้าเว็บ — เปิด LIFF (ได้ตัวตน) แล้วแสดง RegisterScreen
import { useEffect, useState } from "react";

import { initLiff, type LiffSession } from "./liff-init";
import { RegisterScreen } from "./screens/RegisterScreen";

type InitState =
  | { status: "loading" }
  | { status: "ready"; session: LiffSession }
  | { status: "error"; message: string };

export function App() {
  const [state, setState] = useState<InitState>({ status: "loading" });

  useEffect(() => {
    initLiff()
      .then((session) => setState({ status: "ready", session }))
      .catch((err) => setState({ status: "error", message: err?.message ?? "เปิด LINE ไม่สำเร็จ" }));
  }, []);

  if (state.status === "loading") {
    return <div className="screen center-screen"><span className="spinner" /></div>;
  }

  if (state.status === "error") {
    return (
      <div className="screen center-screen">
        <div className="card center">
          <p className="subtle">เปิดหน้านี้ผ่านแอป LINE ไม่สำเร็จ</p>
          <div className="error" role="alert">{state.message}</div>
        </div>
      </div>
    );
  }

  return <RegisterScreen idToken={state.session.idToken} />;
}
