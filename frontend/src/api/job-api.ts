// ถามสถานะงานสแกน — หน้า ProcessingScreen ถามซ้ำจนกว่าจะเสร็จ
import { isPreviewMode } from "../config";
import { api, sleep } from "./client";

export type JobState = "queued" | "processing" | "succeeded" | "failed";

export interface JobStatus {
  job_id: string;
  state: JobState;
  message: string | null;
  points_balance: number | null;
}

//: โหมดพรีวิว — จำลองว่างานเดินจาก queued → processing → succeeded ตามจำนวนครั้งที่ถาม
const previewPolls = new Map<string, number>();

export async function readJob(jobId: string, idToken: string): Promise<JobStatus> {
  if (isPreviewMode) {
    await sleep(500);
    const count = (previewPolls.get(jobId) ?? 0) + 1;
    previewPolls.set(jobId, count);

    if (count < 2) return { job_id: jobId, state: "processing", message: null, points_balance: null };
    return { job_id: jobId, state: "succeeded", message: null, points_balance: 125 };
  }

  return api.get(`/jobs/${encodeURIComponent(jobId)}`, idToken) as Promise<JobStatus>;
}
