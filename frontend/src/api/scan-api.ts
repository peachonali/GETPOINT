// ส่งรูปใบเสร็จ → ได้ job_id กลับมาทันที (backend ตอบ 202 ไม่รอประมวลผล)
import { isPreviewMode } from "../config";
import { ApiError, api, sleep } from "./client";

export interface SubmitScanResult {
  job_id: string;
  state: string;
}

//: โหมดพรีวิว (ยังไม่มี LIFF/backend) — จำลองว่าเข้าคิวสำเร็จ เพื่อให้ลองกดดู flow ได้
let previewCounter = 0;

export async function submitScan(file: File, idToken: string): Promise<SubmitScanResult> {
  if (isPreviewMode) {
    await sleep(700);
    previewCounter += 1;
    return { job_id: `preview-job-${previewCounter}`, state: "queued" };
  }

  const form = new FormData();
  form.append("image", file);
  return api.post("/scan", idToken, form) as Promise<SubmitScanResult>;
}

export { ApiError };
