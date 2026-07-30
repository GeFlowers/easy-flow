import type { Message, Thread } from "@langchain/langgraph-sdk";

import type { Todo } from "../todos";

/** 线程目标的当前状态及最近一次评估结果。 */
export interface GoalState {
  objective: string;
  status: "active";
  created_at: string;
  updated_at: string;
  continuation_count: number;
  max_continuations: number;
  no_progress_count: number;
  max_no_progress_continuations: number;
  last_evaluation?: {
    satisfied: boolean;
    blocker:
      | "none"
      | "missing_evidence"
      | "needs_user_input"
      | "run_failed"
      | "external_wait"
      | "goal_not_met_yet";
    reason: string;
    evidence_summary?: string;
    run_id?: string;
    evaluated_at?: string;
    progress_key?: string;
    stand_down_reason?: string;
  };
}

/** 智能体线程在运行时维护的可渲染状态。 */
export interface AgentThreadState extends Record<string, unknown> {
  title: string;
  messages: Message[];
  artifacts?: string[];
  todos?: Todo[];
  goal?: GoalState | null;
}

/** 提交线程运行时附带的智能体与模型上下文。 */
export interface AgentThreadContext extends Record<string, unknown> {
  thread_id: string;
  model_name: string | undefined;
  thinking_enabled: boolean;
  is_plan_mode: boolean;
  subagent_enabled: boolean;
  reasoning_effort?: "minimal" | "low" | "medium" | "high";
  agent_name?: string;
}

/** 带有 DeerFlow 状态和上下文的 LangGraph 线程。 */
export interface AgentThread extends Thread<AgentThreadState> {
  context?: AgentThreadContext;
}

/** 持久化运行事件中的单条消息及其元数据。 */
export interface RunMessage {
  run_id: string;
  seq?: number;
  content: Message;
  metadata: {
    caller: string;
    [key: string]: unknown;
  };
  created_at: string;
}

/** 线程累计令牌用量接口的响应结构。 */
export interface ThreadTokenUsageResponse {
  thread_id: string;
  total_tokens: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_runs: number;
  by_model: Record<string, { tokens: number; runs: number }>;
  by_caller: {
    lead_agent: number;
    subagent: number;
    middleware: number;
  };
}
