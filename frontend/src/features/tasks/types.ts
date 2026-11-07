import type { AIMessage } from "@langchain/langgraph-sdk";

import type { TokenUsage } from "../messages/usage";

import type { SubtaskStep } from "./steps";

/** 描述子代理任务在前端中的完整生命周期状态。 */
export interface Subtask {
  id: string;
  status: "in_progress" | "completed" | "failed";
  subagent_type: string;
  description: string;
  /** 本次子代理运行实际选用的 DeerFlow 模型。 */
  modelName?: string;
  /** 子代理运行期间最新上报的累计令牌用量快照。 */
  usage?: TokenUsage;
  latestMessage?: AIMessage;
  /**
   * 子代理按顺序排列的完整步骤历史（助手轮次与工具输出）。
   * 实时从 `task_running` 事件累积，展开历史运行时再回填（#3779），取代旧版仅保留
   * `latestMessage` 的行为。
   */
  steps?: SubtaskStep[];
  prompt: string;
  result?: string;
  error?: string;
  /**
   * 导致运行被护栏上限提前结束的原因（`token_capped`、`turn_capped` 或
   * `loop_capped`）；正常结束时为 `undefined`。状态标签仍保持正常的 `completed` 或
   * `failed`，此字段携带上限细节，后续徽标无需解析结果文本即可展示“已达上限”（#3875 第二阶段）。
   */
  stopReason?: string;
}
