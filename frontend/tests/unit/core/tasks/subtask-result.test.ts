import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "@rstest/core";

import {
  SUBAGENT_ERROR_KEY,
  SUBAGENT_MODEL_NAME_KEY,
  SUBAGENT_RESULT_BRIEF_KEY,
  SUBAGENT_STATUS_KEY,
  SUBAGENT_STOP_REASON_KEY,
  SUBAGENT_TOKEN_USAGE_KEY,
  derivePendingSubtaskStatus,
  hasSubtaskToolResult,
  parseSubtaskResult,
} from "@/core/tasks/subtask-result";

interface ContractFile {
  valid_status_values: string[];
  valid_stop_reason_values: string[];
}

const CONTRACT_PATH = resolve(
  __dirname,
  "../../../../../contracts/subagent_status_contract.json",
);
const CONTRACT: ContractFile = JSON.parse(
  readFileSync(CONTRACT_PATH, "utf-8"),
) as ContractFile;

describe("parseSubtaskResult", () => {
  /**
   * 覆盖“uses legacy task result text when structured metadata is absent”这一可观察行为，防止相关边界在重构后回归。
   */
  it("uses legacy task result text when structured metadata is absent", () => {
    expect(
      parseSubtaskResult(
        "Task Succeeded. Result: investigated and produced a 3-page report",
      ),
    ).toEqual({
      status: "completed",
      result: "investigated and produced a 3-page report",
    });

    expect(
      parseSubtaskResult(
        "Task failed. Error: underlying tool raised RuntimeError",
      ),
    ).toEqual({
      status: "failed",
      error: "Error: underlying tool raised RuntimeError",
    });

    expect(parseSubtaskResult("Task cancelled by user.")).toEqual({
      status: "failed",
      error: "Task cancelled by user.",
    });

    expect(parseSubtaskResult("Task timed out. Error: 900 seconds")).toEqual({
      status: "failed",
      error: "Task timed out. Error: 900 seconds",
    });

    expect(
      parseSubtaskResult(
        "Task polling timed out after 15 minutes. Status: RUNNING",
      ),
    ).toEqual({
      status: "failed",
      error: "Task polling timed out after 15 minutes. Status: RUNNING",
    });

    expect(
      parseSubtaskResult("Error: Tool 'task' failed with TypeError: boom"),
    ).toEqual({
      status: "failed",
      error: "Error: Tool 'task' failed with TypeError: boom",
    });
  });

  /**
   * 覆盖“keeps unknown content-only task results in progress”这一可观察行为，防止相关边界在重构后回归。

   */

  it("keeps unknown content-only task results in progress", () => {
    const parsed = parseSubtaskResult("partial streaming chunk");

    expect(parsed.status).toBe("in_progress");
    expect(parsed.error).toBeUndefined();
    expect(parsed.result).toBeUndefined();
  });
});

describe("hasSubtaskToolResult", () => {
  /**
   * 覆盖“matches a task tool call to its ToolMessage”这一可观察行为，防止相关边界在重构后回归。
   */
  it("matches a task tool call to its ToolMessage", () => {
    const messages = [
      { type: "ai" },
      { type: "tool", tool_call_id: "call_task_1" },
    ] as Message[];

    expect(hasSubtaskToolResult("call_task_1", messages)).toBe(true);
  });

  /**
   * 覆盖“returns false when a task tool call has no ToolMessage”这一可观察行为，防止相关边界在重构后回归。

   */

  it("returns false when a task tool call has no ToolMessage", () => {
    const messages = [
      { type: "ai" },
      { type: "tool", tool_call_id: "call_other" },
    ] as Message[];

    expect(hasSubtaskToolResult("call_task_1", messages)).toBe(false);
  });
});

describe("derivePendingSubtaskStatus", () => {
  /**
   * 覆盖“keeps a task in progress while its own assistant turn is loading”这一可观察行为，防止相关边界在重构后回归。
   */
  it("keeps a task in progress while its own assistant turn is loading", () => {
    const messages = [{ type: "ai" }] as Message[];

    expect(derivePendingSubtaskStatus("call_task_1", messages, true)).toBe(
      "in_progress",
    );
  });

  /**
   * 覆盖“does not revive an earlier unfinished task during a later turn”这一可观察行为，防止相关边界在重构后回归。

   */

  it("does not revive an earlier unfinished task during a later turn", () => {
    const messages = [{ type: "ai" }] as Message[];

    expect(derivePendingSubtaskStatus("call_task_1", messages, false)).toBe(
      "failed",
    );
  });

  /**
   * 覆盖“leaves result parsing to the ToolMessage path when a result exists”这一可观察行为，防止相关边界在重构后回归。

   */

  it("leaves result parsing to the ToolMessage path when a result exists", () => {
    const messages = [
      { type: "ai" },
      { type: "tool", tool_call_id: "call_task_1" },
    ] as Message[];

    expect(derivePendingSubtaskStatus("call_task_1", messages, false)).toBe(
      "in_progress",
    );
  });
});

/**
 * 结构化状态路径（bytedance/deer-flow#3146）。
 *
 * 后端直接写入 `ToolMessage.additional_kwargs.subagent_status`。前端应优先使用它，
 * 而非从内容字符串逆向推断。
 */
describe("parseSubtaskResult — structured additional_kwargs (preferred path)", () => {
  /**
   * 覆盖“uses additional_kwargs.subagent_status when present”这一可观察行为，防止相关边界在重构后回归。
   */
  it("uses additional_kwargs.subagent_status when present", () => {
    const parsed = parseSubtaskResult("Task Succeeded. Result: foo", {
      [SUBAGENT_STATUS_KEY]: "completed",
    });
    expect(parsed.status).toBe("completed");
  });

  /**
   * 覆盖“restores terminal model and token usage metadata”这一可观察行为，防止相关边界在重构后回归。

   */

  it("restores terminal model and token usage metadata", () => {
    expect(
      parseSubtaskResult("Task Succeeded. Result: done", {
        [SUBAGENT_STATUS_KEY]: "completed",
        [SUBAGENT_MODEL_NAME_KEY]: "claude-3-7-sonnet",
        [SUBAGENT_TOKEN_USAGE_KEY]: {
          input_tokens: 100,
          output_tokens: 20,
          total_tokens: 120,
        },
      }),
    ).toMatchObject({
      status: "completed",
      modelName: "claude-3-7-sonnet",
      usage: {
        inputTokens: 100,
        outputTokens: 20,
        totalTokens: 120,
      },
    });
  });

  /**
   * 覆盖“collapses cancelled / timed_out / polling_timed_out to failed for the card UI”这一可观察行为，防止相关边界在重构后回归。

   */

  it("collapses cancelled / timed_out / polling_timed_out to failed for the card UI", () => {
    for (const backendStatus of [
      "cancelled",
      "timed_out",
      "polling_timed_out",
    ]) {
      const parsed = parseSubtaskResult("anything at all", {
        [SUBAGENT_STATUS_KEY]: backendStatus,
      });
      expect(parsed.status).toBe("failed");
    }
  });

  /**
   * 覆盖“renders legacy max_turns_reached (checkpointed under #3949) as a terminal failed pill, not spinning in_progress”这一可观察行为，防止相关边界在重构后回归。

   */

  it("renders legacy max_turns_reached (checkpointed under #3949) as a terminal failed pill, not spinning in_progress", () => {
    // 第一阶段将 `subagent_status: "max_turns_reached"` 写入 ToolMessage
    // additional_kwargs，它会被检入线程历史。第二阶段（#3980）不再生成它，但旧回合
    // 仍携带该值。没有已废弃别名时，hasStructuredSubagentMetadata 保持 true（存在同级键）
    // 而 readStructuredStatus 返回 null -> parseSubtaskResult 返回
    // { status: "in_progress" }，卡片将永远旋转。该别名使其保持终态，与第一阶段对该值的
    // 渲染方式一致。
    const parsed = parseSubtaskResult("ignored content", {
      [SUBAGENT_STATUS_KEY]: "max_turns_reached",
      [SUBAGENT_ERROR_KEY]: "Reached max_turns=150",
      [SUBAGENT_RESULT_BRIEF_KEY]: "investigated 3 of 5 sources",
    });
    expect(parsed.status).toBe("failed");
    expect(parsed.error).toBe("Reached max_turns=150");
    // result 仅附加到 completed 状态标记；旧数据渲染为 failed。
    expect(parsed.result).toBeUndefined();
  });

  /**
   * 覆盖“surfaces stop_reason on a capped run while keeping a normal pill status”这一可观察行为，防止相关边界在重构后回归。

   */

  it("surfaces stop_reason on a capped run while keeping a normal pill status", () => {
    // bytedance/deer-flow#3875 第二阶段：受 token 上限限制的任务产生了最终回答，
    // 因此它是 `completed`，上限信息位于附加的 `subagent_stop_reason` 字段。卡片保持
    // 绿色；stopReason 为未来标记携带上限详情，恢复的部分结果则位于 subagent_result_brief。
    const parsed = parseSubtaskResult("ignored content", {
      [SUBAGENT_STATUS_KEY]: "completed",
      [SUBAGENT_RESULT_BRIEF_KEY]: "investigated 3 of 5 sources",
      [SUBAGENT_STOP_REASON_KEY]: "token_capped",
    });
    expect(parsed.status).toBe("completed");
    expect(parsed.result).toBe("investigated 3 of 5 sources");
    expect(parsed.stopReason).toBe("token_capped");
  });

  /**
   * 覆盖“surfaces stop_reason on a turn-capped run that produced no usable result”这一可观察行为，防止相关边界在重构后回归。

   */

  it("surfaces stop_reason on a turn-capped run that produced no usable result", () => {
    // 没有可用部分结果 -> 后端写入 `failed` + turn_capped。卡片变红；stopReason 仍携带
    // 上限，以便未来标记能展示它。
    const parsed = parseSubtaskResult("ignored content", {
      [SUBAGENT_STATUS_KEY]: "failed",
      [SUBAGENT_ERROR_KEY]: "Reached max_turns=150",
      [SUBAGENT_STOP_REASON_KEY]: "turn_capped",
    });
    expect(parsed.status).toBe("failed");
    expect(parsed.error).toBe("Reached max_turns=150");
    expect(parsed.stopReason).toBe("turn_capped");
  });

  /**
   * 覆盖“ignores an unknown subagent_stop_reason value”这一可观察行为，防止相关边界在重构后回归。

   */

  it("ignores an unknown subagent_stop_reason value", () => {
    // 丢弃无法识别的 stop_reason，确保旧版前端绝不渲染虚假的上限标记。
    const parsed = parseSubtaskResult("ignored content", {
      [SUBAGENT_STATUS_KEY]: "completed",
      [SUBAGENT_STOP_REASON_KEY]: "future_cap_kind",
    });
    expect(parsed.status).toBe("completed");
    expect(parsed.stopReason).toBeUndefined();
  });

  /**
   * 覆盖“uses subagent_error when supplied”这一可观察行为，防止相关边界在重构后回归。

   */

  it("uses subagent_error when supplied", () => {
    const parsed = parseSubtaskResult("ignored content", {
      [SUBAGENT_STATUS_KEY]: "failed",
      [SUBAGENT_ERROR_KEY]: "boom from backend",
    });
    expect(parsed.status).toBe("failed");
    expect(parsed.error).toBe("boom from backend");
  });

  /**
   * 覆盖“ignores empty / non-string subagent_error”这一可观察行为，防止相关边界在重构后回归。

   */

  it("ignores empty / non-string subagent_error", () => {
    const parsed = parseSubtaskResult("ignored content", {
      [SUBAGENT_STATUS_KEY]: "failed",
      [SUBAGENT_ERROR_KEY]: "",
    });
    expect(parsed.status).toBe("failed");
    expect(parsed.error).toBeUndefined();
  });

  /**
   * 覆盖“ignores terminal-looking content when partial structured metadata is present”这一可观察行为，防止相关边界在重构后回归。

   */

  it("ignores terminal-looking content when partial structured metadata is present", () => {
    const parsed = parseSubtaskResult("Task Succeeded. Result: foo", {
      [SUBAGENT_RESULT_BRIEF_KEY]: "structured result without status",
    });
    expect(parsed.status).toBe("in_progress");
    expect(parsed.result).toBeUndefined();
  });

  /**
   * 覆盖“ignores terminal-looking content when the structured status is unknown”这一可观察行为，防止相关边界在重构后回归。

   */

  it("ignores terminal-looking content when the structured status is unknown", () => {
    const parsed = parseSubtaskResult("Task Succeeded. Result: foo", {
      [SUBAGENT_STATUS_KEY]: "renamed_in_v3",
    });
    expect(parsed.status).toBe("in_progress");
  });

  /**
   * 覆盖“structured status overrides misleading content”这一可观察行为，防止相关边界在重构后回归。

   */

  it("structured status overrides misleading content", () => {
    const parsed = parseSubtaskResult("Task Succeeded. Result: this is a lie", {
      [SUBAGENT_STATUS_KEY]: "failed",
    });
    expect(parsed.status).toBe("failed");
    expect(parsed.result).toBeUndefined();
    expect(parsed.error).toBeUndefined();
  });

  /**
   * 覆盖“does not back-fill result from content when structured result metadata is missing”这一可观察行为，防止相关边界在重构后回归。

   */

  it("does not back-fill result from content when structured result metadata is missing", () => {
    const parsed = parseSubtaskResult("Task Succeeded. Result: text-only", {
      [SUBAGENT_STATUS_KEY]: "completed",
    });
    expect(parsed.status).toBe("completed");
    expect(parsed.result).toBeUndefined();
  });

  /**
   * 覆盖“uses bounded structured result metadata when present for completed task”这一可观察行为，防止相关边界在重构后回归。

   */

  it("uses bounded structured result metadata when present for completed task", () => {
    const parsed = parseSubtaskResult("Task Succeeded. Result: text body", {
      [SUBAGENT_STATUS_KEY]: "completed",
      subagent_result_brief: "structured",
      subagent_result_sha256: "a".repeat(64),
    });
    expect(parsed.status).toBe("completed");
    expect(parsed.result).toBe("structured");
  });

  /**
   * 覆盖“does not back-fill error from content when structured error metadata is missing”这一可观察行为，防止相关边界在重构后回归。

   */

  it("does not back-fill error from content when structured error metadata is missing", () => {
    const parsed = parseSubtaskResult(
      "Error: Tool 'task' failed with TypeError: boom",
      {
        [SUBAGENT_STATUS_KEY]: "failed",
      },
    );
    expect(parsed.status).toBe("failed");
    expect(parsed.error).toBeUndefined();
  });

  /**
   * 覆盖“leaves `error` undefined when structured says failed with no error and unrecognised text”这一可观察行为，防止相关边界在重构后回归。

   */

  it("leaves `error` undefined when structured says failed with no error and unrecognised text", () => {
    // 不要将任意内容塞入错误字段——宁可渲染空的 `failed` 状态标记，也不要展示噪音。
    const parsed = parseSubtaskResult("partial streaming chunk", {
      [SUBAGENT_STATUS_KEY]: "failed",
    });
    expect(parsed.status).toBe("failed");
    expect(parsed.error).toBeUndefined();
  });
});

/**
 * 结构化子代理状态字段的跨语言契约测试。后端和前端共享枚举值，但任务结果文本
 * 不再属于连线契约的一部分。
 */
describe("parseSubtaskResult — shared contract fixture", () => {
  const expectedCardStatus = (backendStatus: string): string => {
    if (backendStatus === "completed") return "completed";
    return "failed";
  };

  for (const status of CONTRACT.valid_status_values) {
    it(`maps structured status: ${status}`, () => {
      const parsed = parseSubtaskResult("ignored content", {
        [SUBAGENT_STATUS_KEY]: status,
      });
      expect(parsed.status).toBe(expectedCardStatus(status));
    });
  }

  for (const stopReason of CONTRACT.valid_stop_reason_values) {
    it(`carries stop_reason through unchanged: ${stopReason}`, () => {
      const parsed = parseSubtaskResult("ignored content", {
        [SUBAGENT_STATUS_KEY]: "completed",
        [SUBAGENT_RESULT_BRIEF_KEY]: "partial work",
        [SUBAGENT_STOP_REASON_KEY]: stopReason,
      });
      expect(parsed.stopReason).toBe(stopReason);
    });
  }
});
