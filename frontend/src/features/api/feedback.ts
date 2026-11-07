import { getBackendBaseURL } from "../config";

import { fetch } from "./fetcher";

/** 线程运行反馈接口返回的持久化数据。 */
export interface FeedbackData {
  feedback_id: string;
  rating: number;
  comment: string | null;
}

/** 为指定线程运行新增或更新评分和可选评论。 */
export async function upsertFeedback(
  threadId: string,
  runId: string,
  rating: number,
  comment?: string,
): Promise<FeedbackData> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}/feedback`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating, comment: comment ?? null }),
    },
  );
  if (!res.ok) {
    throw new Error(`Failed to submit feedback: ${res.status}`);
  }
  return res.json();
}

/** 删除指定线程运行的反馈；不存在的反馈视为已删除。 */
export async function deleteFeedback(
  threadId: string,
  runId: string,
): Promise<void> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}/feedback`,
    { method: "DELETE" },
  );
  if (!res.ok && res.status !== 404) {
    throw new Error(`Failed to delete feedback: ${res.status}`);
  }
}
