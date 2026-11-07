import { fetch } from "../api/fetcher";
import { getBackendBaseURL } from "../config";

import { eventsToSteps, type SubtaskStep } from "./steps";

/** 单次请求默认页大小，与事件端点默认值一致。 */
const SUBTASK_STEPS_PAGE_SIZE = 500;
/** 分页安全上限，防止异常游标无限循环。 */
const SUBTASK_STEPS_MAX_PAGES = 100;

type FetchedEvent = Parameters<typeof eventsToSteps>[0][number] & {
  seq?: number;
};

/**
 * 获取历史运行中子任务已持久化的步骤历史（#3779）。
 *
 * 服务端限定为该 `taskId`（及 `subagent.step` 事件），用 `after_seq` 游标向前分页直至短页，
 * 使运行级事件上限不会截断子代理步骤时间线，即使运行很长或包含多个子代理。子任务卡片展开时，
 * 若实时 SSE 步骤已消失（例如页面重载后），以此回填步骤。
 */
export async function fetchSubtaskSteps(
  threadId: string,
  runId: string,
  taskId: string,
  pageSize: number = SUBTASK_STEPS_PAGE_SIZE,
): Promise<SubtaskStep[]> {
  const base = `${getBackendBaseURL()}/api/threads/${encodeURIComponent(
    threadId,
  )}/runs/${encodeURIComponent(runId)}/events`;

  const events: FetchedEvent[] = [];
  let afterSeq: number | undefined;

  for (let page = 0; page < SUBTASK_STEPS_MAX_PAGES; page++) {
    const params = new URLSearchParams({
      event_types: "subagent.step",
      task_id: taskId,
      limit: String(pageSize),
    });
    if (afterSeq !== undefined) {
      params.set("after_seq", String(afterSeq));
    }

    const res = await fetch(`${base}?${params.toString()}`);
    if (!res.ok) {
      throw new Error(`Failed to fetch subtask steps: ${res.status}`);
    }
    const batch = (await res.json()) as FetchedEvent[];
    events.push(...batch);

    if (batch.length < pageSize) {
      break;
    }
    const lastSeq = batch[batch.length - 1]?.seq;
    if (lastSeq === undefined) {
      break; // 无法推进游标，停止而非无限重复请求第 0 页。
    }
    afterSeq = lastSeq;
  }

  return eventsToSteps(events, taskId);
}
